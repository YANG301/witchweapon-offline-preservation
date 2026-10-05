package com.codex.witchweapon;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.charset.CodingErrorAction;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Iterator;
import java.util.Objects;
import java.util.UUID;
import java.util.ArrayList;
import java.util.List;
import java.util.Comparator;

/** Private, append-only administration evidence, separate from AtomicFile's transient .bak. */
final class AdminJournal {
    private static final long MAX_SNAPSHOT = 32L << 20;
    private AdminJournal() {}

    static final class Record {
        private final Path auditDir;
        private final JSONObject entry;
        private final String id;
        Record(Path auditDir, JSONObject entry, String id) {
            this.auditDir=auditDir;this.entry=entry;this.id=id;
        }
        String id(){return id;}
        void committed(long revision) throws Exception {
            if(revision!=entry.getLong("revisionBefore")+1)
                throw new IOException("Unexpected committed save revision");
            JSONObject committed=new JSONObject(entry.toString());
            committed.put("status","committed");
            committed.put("revisionAfter",revision);
            committed.put("committedAt",System.currentTimeMillis());
            atomicWrite(auditDir.resolve(id+"-committed.json"),json(committed));
        }
    }

    static Record prepare(File base,long revision,String reason,JSONObject oldSave,JSONObject newSave) throws Exception {
        return prepare(base,revision,reason,oldSave,newSave,"edit",null);
    }
    static Record prepare(File base,long revision,String reason,JSONObject oldSave,JSONObject newSave,
            String kind,JSONArray changes) throws Exception {
        if(revision<0 || revision==Long.MAX_VALUE)throw new IOException("Save revision cannot be incremented");
        Path live=base.toPath().toAbsolutePath().normalize();
        Path accountDir=live.getParent();
        Path usersDir=accountDir==null?null:accountDir.getParent();
        Path dataDir=usersDir==null?null:usersDir.getParent();
        if(dataDir==null || !"users".equals(usersDir.getFileName().toString()))
            throw new IOException("Unexpected account save directory");
        byte[] original=regularBytes(live);
        // Do not accept an out-of-process edit or a stale in-memory snapshot.
        if(!sameJson(oldSave,parseSave(original)))
            throw new IOException("Live save does not match the in-memory state");
        String id=UUID.randomUUID().toString();
        String accountId=accountDir.getFileName().toString();
        Path backupDir=dataDir.resolve("admin-backups").resolve(accountId);
        Path auditDir=dataDir.resolve("admin-audit").resolve(accountId);
        privateDir(backupDir.getParent());privateDir(auditDir.getParent());
        privateDir(backupDir);privateDir(auditDir);
        Path snapshot=backupDir.resolve(id+".json");
        atomicWrite(snapshot,original);
        JSONObject entry=new JSONObject();
        entry.put("id",id);entry.put("status","prepared");
        entry.put("accountId",accountId);entry.put("source","admin-web");
        entry.put("preparedAt",System.currentTimeMillis());
        entry.put("revisionBefore",revision);entry.put("revisionExpectedAfter",revision+1);
        entry.put("snapshot",dataDir.relativize(snapshot).toString().replace('\\','/'));
        entry.put("snapshotSha256",sha256(original));entry.put("reason",reason);
        entry.put("kind",kind);entry.put("bytes",original.length);
        if(changes!=null)entry.put("changes",changes);
        if(!oldSave.getString("name").equals(newSave.getString("name"))){
            entry.put("oldName",oldSave.getString("name"));entry.put("newName",newSave.getString("name"));
        }
        if(oldSave.getLong("gold")!=newSave.getLong("gold")){
            entry.put("oldGold",oldSave.getLong("gold"));entry.put("newGold",newSave.getLong("gold"));
        }
        atomicWrite(auditDir.resolve(id+"-prepared.json"),json(entry));
        return new Record(auditDir,entry,id);
    }

    static JSONObject backup(File base,long revision,String reason,JSONObject current)throws Exception{
        Path live=base.toPath().toAbsolutePath().normalize(),data=dataDirectory(live);
        byte[] bytes=regularBytes(live);
        if(!sameJson(current,parseSave(bytes)))throw new IOException("Live save does not match the in-memory state");
        String account=live.getParent().getFileName().toString(),id=UUID.randomUUID().toString();
        Path backups=data.resolve("admin-backups").resolve(account),audits=data.resolve("admin-audit").resolve(account);
        privateDir(backups.getParent());privateDir(audits.getParent());privateDir(backups);privateDir(audits);
        JSONObject entry=new JSONObject().put("id",id).put("accountId",account).put("source","admin-web")
            .put("status","backup").put("kind","manual").put("preparedAt",System.currentTimeMillis())
            .put("revisionBefore",revision).put("reason",reason).put("snapshotSha256",sha256(bytes))
            .put("bytes",bytes.length).put("snapshot","admin-backups/"+account+"/"+id+".json");
        atomicWrite(backups.resolve(id+".json"),bytes);
        atomicWrite(audits.resolve(id+"-backup.json"),json(entry));
        return new JSONObject().put("backup",item(entry,bytes.length));
    }
    static JSONObject backups(File base)throws Exception{
        Path live=base.toPath().toAbsolutePath().normalize(),data=dataDirectory(live);
        String account=live.getParent().getFileName().toString();
        Path audits=data.resolve("admin-audit").resolve(account);
        List<JSONObject> items=new ArrayList<JSONObject>();
        if(Files.exists(audits,LinkOption.NOFOLLOW_LINKS)){
            safePath(audits);
            if(!Files.isDirectory(audits,LinkOption.NOFOLLOW_LINKS))throw new IOException("Unsafe audit directory");
            int count=0;
            try(DirectoryStream<Path> records=Files.newDirectoryStream(audits)){
                for(Path path:records){
                    String name=path.getFileName().toString();
                    if(!name.matches("[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}-(?:prepared|backup)\\.json"))continue;
                    if(++count>10000)throw new IOException("Too many administrator snapshots");
                    JSONObject entry=parseSave(regularBytes(path));
                    String id=name.substring(0,36);validateEntry(entry,account,id);
                    Path snapshot=data.resolve("admin-backups").resolve(account).resolve(id+".json");
                    safePath(snapshot);
                    if(!Files.isRegularFile(snapshot,LinkOption.NOFOLLOW_LINKS))throw new IOException("Snapshot is missing");
                    long size=Files.size(snapshot);if(size>MAX_SNAPSHOT)throw new IOException("Snapshot exceeds limit");
                    items.add(item(entry,size));
                }
            }
        }
        items.sort(new Comparator<JSONObject>(){public int compare(JSONObject a,JSONObject b){
            return Long.compare(b.optLong("createdAt"),a.optLong("createdAt"));}});
        JSONArray result=new JSONArray();for(JSONObject entry:items)result.put(entry);
        return new JSONObject().put("items",result);
    }
    private static final class Snapshot {
        final byte[] bytes;final JSONObject envelope;
        Snapshot(byte[] bytes,JSONObject envelope){this.bytes=bytes;this.envelope=envelope;}
    }
    static JSONObject readBackup(File base,String id)throws Exception{return snapshot(base,id).envelope;}
    static byte[] readBackupBytes(File base,String id)throws Exception{return snapshot(base,id).bytes;}
    private static Snapshot snapshot(File base,String id)throws Exception{
        if(id==null || !id.matches("[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}"))
            throw new LocalSave.AdminValidation("Invalid backup ID");
        Path live=base.toPath().toAbsolutePath().normalize(),data=dataDirectory(live);
        String account=live.getParent().getFileName().toString();
        Path audits=data.resolve("admin-audit").resolve(account);
        Path prepared=audits.resolve(id+"-prepared.json"),manual=audits.resolve(id+"-backup.json");
        Path record=Files.exists(prepared,LinkOption.NOFOLLOW_LINKS)?prepared:manual;
        if(!Files.exists(record,LinkOption.NOFOLLOW_LINKS))throw new LocalSave.AdminMissing();
        JSONObject entry=parseSave(regularBytes(record));validateEntry(entry,account,id);
        byte[] bytes=regularBytes(data.resolve("admin-backups").resolve(account).resolve(id+".json"));
        if(!sha256(bytes).equals(entry.getString("snapshotSha256")))throw new IOException("Snapshot checksum mismatch");
        JSONObject save=parseSave(bytes);
        if(save.optInt("version",0)!=1 || save.optLong("saveRevision",0)!=entry.getLong("revisionBefore"))
            throw new IOException("Snapshot version or revision mismatch");
        JSONObject envelope=new JSONObject().put("version",1).put("accountId",account).put("backupId",id)
            .put("revision",Long.toString(entry.getLong("revisionBefore")))
            .put("createdAt",entry.getLong("preparedAt")).put("sha256",entry.getString("snapshotSha256"))
            .put("save",save);
        return new Snapshot(bytes,envelope);
    }
    private static JSONObject item(JSONObject entry,long bytes)throws Exception{
        return new JSONObject().put("id",entry.getString("id")).put("createdAt",entry.getLong("preparedAt"))
            .put("revision",Long.toString(entry.getLong("revisionBefore"))).put("reason",entry.getString("reason"))
            .put("kind",entry.optString("kind","edit")).put("sha256",entry.getString("snapshotSha256"))
            .put("bytes",bytes);
    }
    private static void validateEntry(JSONObject entry,String account,String id)throws Exception{
        if(!id.equals(entry.optString("id")) || !account.equals(entry.optString("accountId")) ||
            !"admin-web".equals(entry.optString("source")) ||
            !("prepared".equals(entry.optString("status"))||"backup".equals(entry.optString("status"))) ||
            !entry.optString("snapshotSha256").matches("[0-9a-f]{64}") ||
            !("admin-backups/"+account+"/"+id+".json").equals(entry.optString("snapshot")) ||
            entry.optLong("revisionBefore",-1)<0 || entry.optLong("preparedAt",-1)<0)
            throw new IOException("Invalid snapshot record");
    }
    private static Path dataDirectory(Path live)throws IOException{
        Path account=live.getParent(),users=account==null?null:account.getParent(),data=users==null?null:users.getParent();
        if(data==null || !"users".equals(users.getFileName().toString()))throw new IOException("Unexpected account directory");
        safePath(live);return data;
    }
    static JSONObject parseSave(byte[] bytes)throws Exception{
        String text=StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();
        return new JSONObject(text);
    }
    static void safePath(Path path)throws IOException{
        Path absolute=path.toAbsolutePath().normalize();
        for(Path component=absolute;component!=null;component=component.getParent()){
            if(!Files.exists(component,LinkOption.NOFOLLOW_LINKS))continue;
            if(Files.isSymbolicLink(component) || !component.toRealPath().equals(component.toAbsolutePath().normalize()))
                throw new IOException("Linked administrator storage path");
        }
    }
    static byte[] regularBytes(Path path)throws IOException{
        safePath(path);
        if(!Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)||Files.size(path)>MAX_SNAPSHOT)
            throw new IOException("Missing or oversized administrator storage file");
        byte[] bytes=Files.readAllBytes(path);if(bytes.length>MAX_SNAPSHOT)throw new IOException("Administrator storage file exceeds limit");
        return bytes;
    }

    private static byte[] json(JSONObject data) throws Exception {
        return (data.toString(2)+"\n").getBytes(StandardCharsets.UTF_8);
    }
    static boolean sameJson(Object left,Object right) {
        if(left instanceof JSONObject && right instanceof JSONObject){
            JSONObject a=(JSONObject)left,b=(JSONObject)right;
            if(a.length()!=b.length())return false;
            for(Iterator<String> it=a.keys();it.hasNext();){
                String key=it.next();
                if(!b.has(key)||!sameJson(a.opt(key),b.opt(key)))return false;
            }
            return true;
        }
        if(left instanceof JSONArray && right instanceof JSONArray){
            JSONArray a=(JSONArray)left,b=(JSONArray)right;
            if(a.length()!=b.length())return false;
            for(int i=0;i<a.length();i++)if(!sameJson(a.opt(i),b.opt(i)))return false;
            return true;
        }
        return Objects.equals(left,right) || (left instanceof Number && right instanceof Number &&
            left.toString().equals(right.toString()));
    }
    private static String sha256(byte[] data) throws NoSuchAlgorithmException {
        byte[] hash=MessageDigest.getInstance("SHA-256").digest(data);
        StringBuilder out=new StringBuilder(hash.length*2);
        for(byte value:hash)out.append(String.format("%02x",value&0xff));
        return out.toString();
    }
    private static void privateDir(Path dir) throws IOException {
        safePath(dir);
        Files.createDirectories(dir);
        if(Files.isSymbolicLink(dir) || !Files.isDirectory(dir,LinkOption.NOFOLLOW_LINKS))
            throw new IOException("Unsafe admin record directory");
        if(Files.getFileStore(dir).supportsFileAttributeView("posix"))
            Files.setPosixFilePermissions(dir,PosixFilePermissions.fromString("rwx------"));
    }
    private static void atomicWrite(Path target,byte[] data) throws IOException {
        Path temp=Files.createTempFile(target.getParent(),".admin-",".new");
        try {
            if(Files.getFileStore(temp).supportsFileAttributeView("posix"))
                Files.setPosixFilePermissions(temp,PosixFilePermissions.fromString("rw-------"));
            try(FileOutputStream out=new FileOutputStream(temp.toFile())){
                out.write(data);out.flush();out.getFD().sync();
            }
            Files.move(temp,target,StandardCopyOption.ATOMIC_MOVE);
            if(Files.getFileStore(target.getParent()).supportsFileAttributeView("posix")){
                try(FileChannel directory=FileChannel.open(target.getParent(),StandardOpenOption.READ)){
                    directory.force(true);
                }
            }else{
                try(FileChannel directory=FileChannel.open(target.getParent(),StandardOpenOption.READ)){
                    directory.force(true);
                }catch(IOException ignored){ /* Windows cannot fsync directories. */ }
            }
        }finally{Files.deleteIfExists(temp);}
    }
}
