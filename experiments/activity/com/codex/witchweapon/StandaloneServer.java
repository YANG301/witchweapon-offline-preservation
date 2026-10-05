package com.codex.witchweapon;

import com.codex.witchweapon.host.PersistenceException;
import com.sun.net.httpserver.*;
import org.json.*;
import java.io.*;
import java.net.*;
import java.nio.*;
import java.nio.channels.*;
import java.nio.charset.*;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.*;
import java.util.regex.Pattern;

/** Multi-account loopback host for the original game's protobuf endpoints. */
public final class StandaloneServer {
    private static final int MAX_BODY = 1048576;
    private static final Pattern ACCOUNT_ID = Pattern.compile("[A-Za-z0-9_-]{22}");
    private static final Set<String> COSMETIC_TRANSPORT_FIELDS = Collections.unmodifiableSet(
        new HashSet<String>(Arrays.asList("enc","idempotency","hwid","time","sign")));
    private static final Set<String> CSC_MULTIPART_FIELDS = Collections.unmodifiableSet(
        new HashSet<String>(Arrays.asList("enc","idempotency","hwid","roleid","hp",
            "data","state","servantcardids","servantids","energys","levelid",
            "result","killed","npc","attackdamage","hurt","cure",
            "fashioncardid","time","sign")));
    private final JSONObject responses;
    private final StageCatalog stages;
    private final DailyBattle dailyBattles;
    private final WeaponFurnace weaponFurnace;
    private final Set<String> routes = new HashSet<String>();
    private final Path userData;
    private final ConcurrentHashMap<String,LocalSave> saves = new ConcurrentHashMap<String,LocalSave>();
    private final GuildStore guilds;
    private final byte[] proxySecret;
    private final int port;
    private StandaloneServer(Path responsePath, Path data, int port, String secret) throws Exception {
        this.port = port;
        this.userData = data.resolve("users").toAbsolutePath().normalize();
        this.proxySecret = secret.getBytes(StandardCharsets.UTF_8);
        Files.createDirectories(userData);
        this.guilds = new GuildStore(data.toFile());
        responses = new JSONObject(strictUtf8(Files.readAllBytes(responsePath)));
        if (responses.length() != 241 || responses.optJSONObject("_catalog") == null)
            throw new IOException("Expected the complete 241-entry author response set");
        for (Iterator<String> i = responses.keys(); i.hasNext();) {
            String key = i.next(); if (key.equals("_catalog")) continue;
            JSONObject value = responses.getJSONObject(key);
            if (value.has("base64")) com.codex.witchweapon.host.Base64.decode(value.getString("base64"), 0);
            else if (!value.has("body")) throw new IOException("Response payload missing: " + key);
            if (key.startsWith("/")) {
                int fixture = key.indexOf('#');
                routes.add(fixture < 0 ? key : key.substring(0, fixture));
            }
        }
        // The preserved response set has no original server wave data for
        // guide battles. Add clearly local fixtures in memory after validating
        // the immutable author response count above.
        TutorialBattleFixtures.install(responses);
        stages=StageCatalog.bundled();
        stages.install(responses);
        BarrierLabyrinth.install(responses);
        dailyBattles=DailyBattle.bundled();
        dailyBattles.install(responses);
        weaponFurnace=WeaponFurnace.bundled();
        weaponFurnace.install(responses);
        PreservedBattleCatalog.install(responses);
        LocalActivityLab.install(responses);
        LocalActivityLab.configureRoleCatalog(responses.getJSONObject("_catalog"));
        routes.addAll(LocalActivityLab.routes());
        routes.add("/csc/instance/json");
        // Resolve any charged-but-not-yet-visible guild creation before serving requests.
        guilds.recoverPending(this::existingSaveForAccount);
        guilds.refreshKnownMemberPower(this::existingSaveForAccount,
            responses.getJSONObject("_catalog"));
    }
    private LocalSave saveForAccount(String accountId) throws IOException {
        LocalSave save = saves.get(accountId);
        if (save != null) return save;
        synchronized (saves) {
            save = saves.get(accountId);
            if (save != null) return save;
            Path directory = userData.resolve(accountId).normalize();
            if (!directory.startsWith(userData)) throw new IOException("Invalid account directory");
            Files.createDirectories(directory);
            save = new LocalSave(directory.toFile());
            saves.put(accountId, save);
            return save;
        }
    }
    private LocalSave existingSaveForAccount(String accountId) throws IOException {
        Path directory=userData.resolve(accountId).normalize();
        if(!directory.startsWith(userData))throw new IOException("Invalid account directory");
        Path base=directory.resolve("offline_save_v1.json");
        Path backup=directory.resolve("offline_save_v1.json.bak");
        if(!Files.isRegularFile(base,LinkOption.NOFOLLOW_LINKS) &&
                !Files.isRegularFile(backup,LinkOption.NOFOLLOW_LINKS))
            throw new LocalSave.AdminMissing();
        LocalSave save=saves.get(accountId);
        if(save!=null)return save;
        synchronized(saves){
            save=saves.get(accountId);
            if(save==null){
                save=new LocalSave(directory.toFile());
                saves.put(accountId,save);
            }
            return save;
        }
    }
    private static String strictUtf8(byte[] bytes) throws CharacterCodingException {
        return StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();
    }
    static JSONObject responseFixture(JSONObject responses,String path){
        // GetRestrictedRoleInfoLogic parses RoleCombatInfoProto directly.
        // The author's challenge seed is empty; its ordinary combat seed has
        // that complete protobuf and is personalized by LocalSave below.
        return responses.optJSONObject(path.equals("/challenge/combat/role/info")
            ? "/combat/role/info" : path);
    }
    private static final class BadRequest extends IOException {
        final int status;
        BadRequest(int status, String message) { super(message); this.status = status; }
    }
    private static String formDecode(String text) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        for (int i = 0; i < text.length(); i++) {
            char c = text.charAt(i);
            if (c == '+') out.write(' ');
            else if (c == '%') {
                if (i + 2 >= text.length()) throw new BadRequest(400, "Invalid form escape");
                int a = Character.digit(text.charAt(++i), 16), b = Character.digit(text.charAt(++i), 16);
                if (a < 0 || b < 0) throw new BadRequest(400, "Invalid form escape");
                out.write((a << 4) | b);
            } else {
                if (c > 127) throw new BadRequest(400, "Form text must use UTF-8 percent encoding");
                out.write(c);
            }
        }
        try { return strictUtf8(out.toByteArray()); }
        catch (CharacterCodingException e) { throw new BadRequest(400, "Invalid UTF-8 form"); }
    }
    private static Map<String,String> readForm(HttpExchange e) throws IOException {
        return readForm(e, null);
    }
    private static Map<String,String> readForm(HttpExchange e, String path) throws IOException {
        String length = e.getRequestHeaders().getFirst("Content-Length");
        if (e.getRequestHeaders().getFirst("Transfer-Encoding") != null)
            throw new BadRequest(400, "Chunked requests are not supported");
        int expected = 0;
        if (length != null) {
            try { expected = Integer.parseInt(length); }
            catch (NumberFormatException ex) { throw new BadRequest(400, "Invalid Content-Length"); }
            if (expected < 0 || expected > MAX_BODY) throw new BadRequest(413, "Request too large");
        }
        byte[] bytes = new byte[expected]; int total = 0;
        try {
            while (total < expected) {
                int n = e.getRequestBody().read(bytes, total, expected - total);
                if (n < 0) throw new BadRequest(400, "Truncated request body");
                total += n;
            }
        } catch (IOException ex) { throw new BadRequest(400, "Truncated request body"); }
        return parseFormBody(path, e.getRequestHeaders().getFirst("Content-Type"), bytes);
    }
    static Map<String,String> parseFormBody(String path, String type, byte[] bytes) throws IOException {
        if (bytes.length > MAX_BODY) throw new BadRequest(413, "Request too large");
        if (bytes.length > 0 && type != null &&
            !type.toLowerCase(Locale.ROOT).startsWith("application/x-www-form-urlencoded")) {
            // BestHTTP's Automatic form mode switches to multipart when any
            // AddField value exceeds 256 characters. CSC battle data does.
            // Accept only that native format on its settlement route.
            if ("/csc/normal/commit".equals(path)) return parseCscMultipart(type, bytes);
            throw new BadRequest(415, "Expected form body");
        }
        String form;
        try { form = strictUtf8(bytes); }
        catch (CharacterCodingException ex) { throw new BadRequest(400, "Invalid UTF-8 body"); }
        Map<String,String> args = new LinkedHashMap<String,String>();
        if (form.isEmpty()) return args;
        for (String pair : form.split("&", -1)) {
            String[] kv = pair.split("=", 2);
            if (kv.length != 2) throw new BadRequest(400, "Expected key=value form entry");
            String key = formDecode(kv[0]), value = formDecode(kv[1]);
            if (key.isEmpty() || args.containsKey(key)) throw new BadRequest(400, "Empty or duplicate form key");
            args.put(key, value);
        }
        return args;
    }
    private static Map<String,String> parseCscMultipart(String type, byte[] bytes) throws IOException {
        // ARM64 BestHTTP.HTTPMultiPartForm writes a quoted boundary made of
        // this prefix plus Int32.ToString("X"). Reject arbitrary MIME bodies.
        String prefix = "multipart/form-data; boundary=\"BestHTTP_HTTPMultiPartForm_";
        if (!type.startsWith(prefix) || !type.endsWith("\""))
            throw new BadRequest(415, "Unsupported CSC body type");
        String hex = type.substring(prefix.length(), type.length() - 1);
        if (!hex.matches("[0-9A-F]{1,8}"))
            throw new BadRequest(415, "Unsupported CSC boundary");
        String boundary = "BestHTTP_HTTPMultiPartForm_" + hex;
        String body = new String(bytes, StandardCharsets.ISO_8859_1);
        String delimiter = "--" + boundary;
        String nextDelimiter = "\r\n" + delimiter;
        if (!body.startsWith(delimiter + "\r\n"))
            throw new BadRequest(400, "Malformed CSC multipart body");
        int cursor = delimiter.length() + 2;
        Map<String,String> args = new LinkedHashMap<String,String>();
        while (true) {
            if (args.size() >= 32) throw new BadRequest(400, "Too many CSC fields");
            String disposition = "Content-Disposition: form-data; name=\"";
            if (!body.startsWith(disposition, cursor))
                throw new BadRequest(400, "Unsupported CSC multipart field");
            int nameStart = cursor + disposition.length();
            int nameEnd = body.indexOf('"', nameStart);
            if (nameEnd < 0 || nameEnd - nameStart > 64)
                throw new BadRequest(400, "Invalid CSC field name");
            String name = body.substring(nameStart, nameEnd);
            if (!CSC_MULTIPART_FIELDS.contains(name) || args.containsKey(name))
                throw new BadRequest(400, "Invalid or duplicate CSC field");
            // BestHTTP writes both metadata lines for each text field.
            // Content-Length is the UTF-8 byte count, so it also disambiguates
            // a delimiter-like sequence inside the opaque combat data field.
            String metadata = "\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: ";
            if (!body.startsWith(metadata, nameEnd + 1))
                throw new BadRequest(400, "Unsupported CSC field headers");
            int lengthStart = nameEnd + 1 + metadata.length();
            int lengthEnd = body.indexOf("\r\n\r\n", lengthStart);
            if (lengthEnd < 0 || lengthEnd - lengthStart > 7)
                throw new BadRequest(400, "Invalid CSC field length");
            String decimal = body.substring(lengthStart, lengthEnd);
            if (!decimal.matches("0|[1-9][0-9]{0,6}"))
                throw new BadRequest(400, "Invalid CSC field length");
            int fieldLength = Integer.parseInt(decimal);
            int valueStart = lengthEnd + 4;
            if (fieldLength > bytes.length - valueStart)
                throw new BadRequest(400, "Truncated CSC field");
            int valueEnd = valueStart + fieldLength;
            if (!body.startsWith(nextDelimiter, valueEnd))
                throw new BadRequest(400, "CSC field length mismatch");
            String value;
            try { value = strictUtf8(Arrays.copyOfRange(bytes, valueStart, valueEnd)); }
            catch (CharacterCodingException ex) { throw new BadRequest(400, "Invalid UTF-8 CSC field"); }
            args.put(name, value);
            cursor = valueEnd + nextDelimiter.length();
            if (body.startsWith("--", cursor)) {
                cursor += 2;
                if (cursor == body.length() ||
                    (cursor + 2 == body.length() && body.startsWith("\r\n", cursor)))
                    return args;
                throw new BadRequest(400, "Unexpected CSC multipart trailer");
            }
            if (!body.startsWith("\r\n", cursor))
                throw new BadRequest(400, "Malformed CSC multipart delimiter");
            cursor += 2;
        }
    }
    private static void send(HttpExchange e, int status, String type, byte[] body) throws IOException {
        e.getResponseHeaders().set("Content-Type", type);
        e.getResponseHeaders().set("Cache-Control", "no-store");
        e.getResponseHeaders().set("X-Content-Type-Options", "nosniff");
        e.sendResponseHeaders(status, body.length == 0 ? 0 : body.length);
        if (body.length > 0) e.getResponseBody().write(body);
    }
    private static final class Reply {
        final int status;
        final String type;
        final byte[] body;
        Reply(int status, String type, byte[] body) { this.status=status; this.type=type; this.body=body; }
    }
    private static Reply error(int status, String code) {
        // No request body, password, token, or filesystem detail is included.
        return new Reply(status, "application/json; charset=utf-8", ("{\"error\":\"" + code + "\"}").getBytes(StandardCharsets.UTF_8));
    }
    private Reply resolve(HttpExchange e) throws Exception {
        String path = e.getRequestURI().getRawPath();
            if (!e.getRemoteAddress().getAddress().isLoopbackAddress()) throw new BadRequest(403, "Local only");
            String origin = e.getRequestHeaders().getFirst("Origin");
            if (origin != null && !origin.equals("http://127.0.0.1:" + port) && !origin.equals("http://localhost:" + port))
                throw new BadRequest(403, "Cross-origin request refused");
            if (!e.getRequestMethod().equals("GET") && !e.getRequestMethod().equals("POST"))
                throw new BadRequest(405, "Method not allowed");
            if (path.equals("/health")) {
                return new Reply(200, "application/json; charset=utf-8", new JSONObject()
                    .put("status","ok").put("mode","account-isolated").put("responseEntries",241)
                    .put("mainlineStages",235).put("playableMainlineStages",stages.supportedCount())
                    .put("campaignProfile",stages.profile())
                    .put("preservedBattleStages",PreservedBattleCatalog.count())
                    .put("allMainlineUnlocked",stages.openAllMainline())
                    .toString().getBytes(StandardCharsets.UTF_8));
            }
            List<String> secrets = e.getRequestHeaders().get("X-WW-Proxy-Secret");
            if (secrets == null || secrets.size() != 1 || !MessageDigest.isEqual(proxySecret, secrets.get(0).getBytes(StandardCharsets.UTF_8)))
                throw new BadRequest(403, "Proxy authentication required");
            String accountId = e.getRequestHeaders().getFirst("X-WW-Account-ID");
            if (accountId == null || !ACCOUNT_ID.matcher(accountId).matches())
                throw new BadRequest(403, "Account identity required");
            if (path.equals("/__state")) {
                if (!e.getRequestMethod().equals("GET")) throw new BadRequest(405, "State is read only");
                LocalSave accountSave = saveForAccount(accountId);
                String mirror = accountSave.mirrorState();
                return new Reply(200, "application/json; charset=utf-8", mirror.getBytes(StandardCharsets.UTF_8));
            }
            if (path.equals("/__role")) {
                if (!e.getRequestMethod().equals("GET") || e.getRequestURI().getRawQuery() != null)
                    throw new BadRequest(405, "Role summary is read only");
                String summary = saveForAccount(accountId).roleSummary();
                return new Reply(200, "application/json; charset=utf-8", summary.getBytes(StandardCharsets.UTF_8));
            }
            if (path.equals("/__guild-membership")) {
                if (!e.getRequestMethod().equals("GET") || e.getRequestURI().getRawQuery()!=null)
                    throw new BadRequest(405,"Guild membership is read only");
                JSONObject role=new JSONObject(existingSaveForAccount(accountId).roleSummary());
                if(!role.getBoolean("exists"))throw new BadRequest(409,"Game role required");
                GuildStore.Identity identity=new GuildStore.Identity(accountId,
                    Long.parseLong(role.getString("roleId")),role.getString("name"),
                    role.optInt("head",1),role.optInt("headBox",1),0);
                String data=guilds.membership(identity);
                return new Reply(200,"application/json; charset=utf-8",data.getBytes(StandardCharsets.UTF_8));
            }
            if (path.equals("/__admin/state")) {
                if (!e.getRequestMethod().equals("GET") || e.getRequestURI().getRawQuery() != null)
                    throw new BadRequest(405, "Admin summary is read only");
                String summary = existingSaveForAccount(accountId).adminSummary();
                return new Reply(200, "application/json; charset=utf-8", summary.getBytes(StandardCharsets.UTF_8));
            }
            if(path.equals("/__admin/save") || path.equals("/__admin/backups")){
                if(!e.getRequestMethod().equals("GET") || e.getRequestURI().getRawQuery()!=null)
                    throw new BadRequest(405,"Admin view requires GET without a query");
                LocalSave accountSave=existingSaveForAccount(accountId);
                String body=path.equals("/__admin/save")
                    ?accountSave.adminSave(responses.getJSONObject("_catalog"),stages):accountSave.adminBackups();
                return new Reply(200,"application/json; charset=utf-8",body.getBytes(StandardCharsets.UTF_8));
            }
            if(Arrays.asList("/__admin/save/preview","/__admin/save/patch","/__admin/backups/create",
                    "/__admin/backups/read","/__admin/backups/preview","/__admin/backups/restore").contains(path)){
                if(!e.getRequestMethod().equals("POST") || e.getRequestURI().getRawQuery()!=null)
                    throw new BadRequest(405,"Admin operation requires POST without a query");
                String type=e.getRequestHeaders().getFirst("Content-Type");
                if(type==null || !type.split(";",2)[0].trim().equalsIgnoreCase("application/x-www-form-urlencoded"))
                    throw new BadRequest(415,"Admin operation requires a form body");
                int bytes;
                try{bytes=Integer.parseInt(e.getRequestHeaders().getFirst("Content-Length"));}
                catch(Exception ex){throw new BadRequest(411,"Admin operation requires Content-Length");}
                if(bytes<1 || bytes>MAX_BODY)throw new BadRequest(413,"Admin operation body exceeds limit");
                Map<String,String> args=readForm(e);LocalSave accountSave=existingSaveForAccount(accountId);
                if(path.equals("/__admin/backups/read"))
                    return new Reply(200,"application/json; charset=utf-8",accountSave.adminBackupRead(args));
                String body;
                if(path.equals("/__admin/backups/create"))body=accountSave.adminBackupCreate(args);
                else if(path.startsWith("/__admin/backups/"))body=accountSave.adminBackupRestore(args,
                    responses.getJSONObject("_catalog"),stages,path.endsWith("/preview"));
                else body=accountSave.adminDataPatch(args,responses.getJSONObject("_catalog"),stages,path.endsWith("/preview"));
                return new Reply(200,"application/json; charset=utf-8",body.getBytes(StandardCharsets.UTF_8));
            }
            if (path.equals("/__admin/patch")) {
                if (!e.getRequestMethod().equals("POST") || e.getRequestURI().getRawQuery() != null)
                    throw new BadRequest(405, "Admin patch requires POST without a query");
                String type=e.getRequestHeaders().getFirst("Content-Type");
                if(type==null || !type.split(";",2)[0].trim().equalsIgnoreCase("application/x-www-form-urlencoded"))
                    throw new BadRequest(415,"Admin patch requires a form body");
                String length=e.getRequestHeaders().getFirst("Content-Length");
                int bytes;
                try { bytes=Integer.parseInt(length); }
                catch(Exception ex) { throw new BadRequest(411,"Admin patch requires Content-Length"); }
                if(bytes<1 || bytes>4096)throw new BadRequest(413,"Admin patch body exceeds limit");
                Map<String,String> args=readForm(e);
                String summary=existingSaveForAccount(accountId).adminPatch(args);
                return new Reply(200,"application/json; charset=utf-8",summary.getBytes(StandardCharsets.UTF_8));
            }
            if (path.equals("/__admin/mail/catalog")) {
                if (!e.getRequestMethod().equals("GET") || e.getRequestURI().getRawQuery()!=null)
                    throw new BadRequest(405,"Mail catalog is read only");
                String body=LocalMail.catalog(responses.getJSONObject("_catalog")).toString();
                return new Reply(200,"application/json; charset=utf-8",body.getBytes(StandardCharsets.UTF_8));
            }
            if (path.equals("/__admin/mail/send")) {
                if (!e.getRequestMethod().equals("POST") || e.getRequestURI().getRawQuery()!=null)
                    throw new BadRequest(405,"Mail send requires POST without a query");
                String type=e.getRequestHeaders().getFirst("Content-Type");
                if(type==null || !type.split(";",2)[0].trim().equalsIgnoreCase("application/x-www-form-urlencoded"))
                    throw new BadRequest(415,"Mail send requires a form body");
                int bytes;
                try{bytes=Integer.parseInt(e.getRequestHeaders().getFirst("Content-Length"));}
                catch(Exception ex){throw new BadRequest(411,"Mail send requires Content-Length");}
                if(bytes<1 || bytes>24576)throw new BadRequest(413,"Mail send body exceeds limit");
                Map<String,String> args=readForm(e);
                String result=existingSaveForAccount(accountId).adminSendMail(args,responses.getJSONObject("_catalog"));
                return new Reply(200,"application/json; charset=utf-8",result.getBytes(StandardCharsets.UTF_8));
            }
            if (path.equals("/mail/updateMailState") || path.equals("/mail/updateSpecialMailState")) {
                if (!e.getRequestMethod().equals("POST") || e.getRequestURI().getRawQuery()!=null)
                    throw new BadRequest(405,"Mail state update requires POST without a query");
                Map<String,String> args=readForm(e);
                byte[] result=saveForAccount(accountId).respond(path,args,new byte[0],
                    responses.getJSONObject("_catalog"));
                return new Reply(200,"application/octet-stream",result);
            }
            if (LocalDaily.claimRoute(path)) {
                if (!e.getRequestMethod().equals("POST") || e.getRequestURI().getRawQuery()!=null)
                    throw new BadRequest(405,"Daily claim requires POST without a query");
                Map<String,String> args=readForm(e);
                byte[] result=saveForAccount(accountId).respond(path,args,new byte[0],
                    responses.getJSONObject("_catalog"));
                return new Reply(200,"application/octet-stream",result);
            }
            if(path.equals("/fashion/select") || path.equals("/game/fashion/select")){
                if(!e.getRequestMethod().equals("POST") || e.getRequestURI().getRawQuery()!=null)
                    throw new BadRequest(405,"Fashion selection requires POST without query");
                String contentType=e.getRequestHeaders().getFirst("Content-Type");
                if(contentType==null || !contentType.split(";",2)[0].trim()
                    .equalsIgnoreCase("application/x-www-form-urlencoded"))
                    throw new BadRequest(415,"Fashion selection requires a form body");
                byte[] result=existingSaveForAccount(accountId).respond(path,readForm(e),
                    new byte[0],responses.getJSONObject("_catalog"));
                return new Reply(200,"application/octet-stream",result);
            }
            if (path.equals("/role/head/change") || path.equals("/role/headbox/change")) {
                if (!e.getRequestMethod().equals("POST") || e.getRequestURI().getRawQuery()!=null)
                    throw new BadRequest(405,"Cosmetic change requires POST without query");
                String type=e.getRequestHeaders().getFirst("Content-Type");
                if(type==null || !type.split(";",2)[0].trim().equalsIgnoreCase("application/x-www-form-urlencoded"))
                    throw new BadRequest(415,"Cosmetic change requires form body");
                Map<String,String> args=readForm(e);
                boolean frame=path.equals("/role/headbox/change");
                String selectedKey=frame?"headbox":"head";
                // The original domainType=3 NetMsgBase appends these five
                // transport fields. Only roleid and the selected cosmetic are
                // used; identity comes from the authenticated account header.
                if(!args.containsKey("roleid") || !args.containsKey(selectedKey))
                    throw new BadRequest(400,"Missing cosmetic form fields");
                for(String key:args.keySet())if(!key.equals("roleid") && !key.equals(selectedKey)
                    && !COSMETIC_TRANSPORT_FIELDS.contains(key))
                    throw new BadRequest(400,"Unknown cosmetic form field");
                JSONObject roleFixture=responses.getJSONObject("/role/role");
                byte[] roleSeed=com.codex.witchweapon.host.Base64.decode(roleFixture.getString("base64"),0);
                existingSaveForAccount(accountId).changeCosmetic(frame,args,roleSeed);
                JSONObject common=responses.getJSONObject("/role/board/change");
                String encoded=common.getString("base64");
                if(!encoded.equals("CgJvaw=="))throw new IOException("Unexpected CommonInfo fixture");
                return new Reply(200,common.optString("type","application/octet-stream"),
                    com.codex.witchweapon.host.Base64.decode(encoded,0));
            }
            if (GuildStore.handles(path)) {
                String guildRoute=path.startsWith("/game/")?path.substring(5):path;
                boolean readOnly=GuildStore.isReadOnly(path);
                if ((!readOnly && !e.getRequestMethod().equals("POST")) ||
                    e.getRequestURI().getRawQuery()!=null)
                    throw new BadRequest(405,"Guild mutation requires POST without query");
                String contentType=e.getRequestHeaders().getFirst("Content-Type");
                if(e.getRequestMethod().equals("POST") && contentType!=null &&
                    !contentType.split(";",2)[0].trim().equalsIgnoreCase("application/x-www-form-urlencoded"))
                    throw new BadRequest(415,"Guild request must be form encoded");
                String length=e.getRequestHeaders().getFirst("Content-Length");
                if(length!=null)try {
                    int bytes=Integer.parseInt(length);
                    if(bytes<0 || bytes>8192)throw new BadRequest(413,"Guild form too large");
                }catch(NumberFormatException ex){throw new BadRequest(400,"Invalid guild form length");}
                LocalSave guildSave=existingSaveForAccount(accountId);
                JSONObject role=new JSONObject(guildSave.roleSummary());
                if(!role.getBoolean("exists"))throw new BadRequest(409,"Game role required");
                GuildStore.Identity identity=new GuildStore.Identity(accountId,
                    Long.parseLong(role.getString("roleId")),role.getString("name"),
                    role.optInt("head",1),role.optInt("headBox",1),
                    guildSave.guildRoleLevel(responses.getJSONObject("_catalog")),
                    guildSave.guildCombatEffectiveness(responses.getJSONObject("_catalog")));
                Map<String,String> guildArgs=readForm(e);
                byte[] body;
                if(guildRoute.equals("/guild/create"))body=guilds.createCharged(identity,guildArgs,guildSave);
                else if(guildRoute.equals("/guild/donateDiamond"))
                    body=guilds.donateCharged(identity,guildArgs,guildSave,true);
                else if(guildRoute.equals("/guild/donateGold"))
                    body=guilds.donateCharged(identity,guildArgs,guildSave,false);
                else if(guildRoute.equals("/guild/sendMercenary"))
                    body=guilds.sendMercenary(identity,guildArgs,guildSave,responses.getJSONObject("_catalog"));
                else if(guildRoute.equals("/guild/recallMercenary"))
                    body=guilds.recallMercenary(identity,guildArgs,guildSave);
                else body=guilds.respond(guildRoute,identity,guildArgs);
                return new Reply(200,"application/octet-stream",body);
            }
            if(path.startsWith("/guild/") || path.startsWith("/game/guild/"))
                return error(501,"guild_feature_unavailable");
            if (VipSystem.handles(path)) {
                if (!e.getRequestMethod().equals("POST") || e.getRequestURI().getRawQuery()!=null)
                    throw new BadRequest(405,"CAPH request requires POST without query");
                String contentType=e.getRequestHeaders().getFirst("Content-Type");
                if(contentType!=null && !contentType.split(";",2)[0].trim()
                    .equalsIgnoreCase("application/x-www-form-urlencoded"))
                    throw new BadRequest(415,"CAPH request must be form encoded");
                byte[] result=existingSaveForAccount(accountId).respond(path,readForm(e),
                    new byte[0],responses.getJSONObject("_catalog"));
                return new Reply(200,"application/octet-stream",result);
            }
            if (RecycleStore.handles(path)) {
                if (!path.endsWith("/get") && !e.getRequestMethod().equals("POST"))
                    throw new BadRequest(405,"Recycle sale requires POST");
                if (e.getRequestURI().getRawQuery()!=null)
                    throw new BadRequest(405,"Recycle request does not accept a query");
                byte[] result=existingSaveForAccount(accountId).respond(path,readForm(e),
                    new byte[0],responses.getJSONObject("_catalog"));
                return new Reply(200,"application/octet-stream",result);
            }
            if (StaminaPurchase.handles(path)) {
                if (!e.getRequestMethod().equals("POST") || e.getRequestURI().getRawQuery()!=null)
                    throw new BadRequest(405,"Stamina request requires POST without query");
                String contentType=e.getRequestHeaders().getFirst("Content-Type");
                if(contentType!=null && !contentType.split(";",2)[0].trim()
                    .equalsIgnoreCase("application/x-www-form-urlencoded"))
                    throw new BadRequest(415,"Stamina request must be form encoded");
                byte[] result=existingSaveForAccount(accountId).respond(path,readForm(e),
                    new byte[0],responses.getJSONObject("_catalog"));
                return new Reply(200,"application/octet-stream",result);
            }
            if (path.equals("/draw/fake")) {
                if (!e.getRequestMethod().equals("POST")) throw new BadRequest(405, "Draw requires POST");
                Map<String,String> args = readForm(e);
                String fakeId = args.get("fakeid");
                if (fakeId == null || !fakeId.matches("[0-9]{1,19}"))
                    throw new BadRequest(400, "Invalid fake draw ID");
                try { Long.parseLong(fakeId); }
                catch (NumberFormatException ex) { throw new BadRequest(400, "Invalid fake draw ID"); }
                // The original client parses CommonInfo here. This presentation
                // action must not run the real draw handler or change the save.
                JSONObject common = responses.getJSONObject("/login/complete");
                String encoded = common.getString("base64");
                if (!encoded.equals("CgJvaxIA")) throw new IOException("Unexpected CommonInfo fixture");
                return new Reply(200, common.optString("type", "application/octet-stream"),
                    com.codex.witchweapon.host.Base64.decode(encoded, 0));
            }
            // Recognize fixture-only routes before fixtureKey can initialize the save.
            if (!routes.contains(path) && !path.endsWith(".env") && !path.endsWith(".mapping"))
                return error(404, "unknown_route");
            Map<String,String> args = readForm(e, path);
            LocalSave save = saveForAccount(accountId);
            String taskPath=path.startsWith("/game/")?path.substring(5):path;
            if(taskPath.equals("/task/update")||taskPath.equals("/task/updatemore")||
               taskPath.equals("/task/all")||taskPath.equals("/achievement/all")||
               taskPath.equals("/achievement/update")){
                // Never trust a client-supplied guild flag. Verify this account
                // against the shared guild store before taking the save lock.
                args=new LinkedHashMap<String,String>(args);
                args.remove("__verifiedGuildMember");
                JSONObject role=new JSONObject(save.roleSummary());
                boolean member=role.optBoolean("exists",false)&&
                    guilds.isMember(accountId,Long.parseLong(role.getString("roleId")));
                args.put("__verifiedGuildMember",member?"1":"0");
            }
            // Selection and processing must observe the same LocalSave state. The author's
            // synchronized methods alone leave a gap between these two operations.
            synchronized (save) {
            if(LocalActivityLab.direct(path)){
                String labPath=LocalActivityLab.normalize(path);
                JSONObject template=responseFixture(responses,labPath.equals("/ap/getRoleInfo")
                    ?"/combat/role/info":"/ap/instance/get");
                byte[] seed=labPath.equals("/ap/getRoleInfo") || labPath.equals("/ap/instance/get") || labPath.equals("/ap/getInfo")
                    ?com.codex.witchweapon.host.Base64.decode(template.getString("base64"),0):new byte[0];
                byte[] result=save.respond(path,args,seed,responses.optJSONObject("_catalog"),null,stages,dailyBattles,weaponFurnace);
                return new Reply(200,"application/octet-stream",result);
            }
            JSONObject response = responseFixture(responses,path);
            if(path.equals("/csc/instance/json") || path.equals("/csc/mob")){
                String original=path.equals("/csc/mob")?"/combat/mob/info":"/combat/mob/json";
                Map<String,String> mazeArgs=new LinkedHashMap<String,String>(args);
                mazeArgs.put("instanceid",Long.toString(StageCatalog.MAZE_TRIAL));
                response=responses.optJSONObject(save.fixtureKey(original,mazeArgs));
                if(response==null)return error(422,"maze_complete_or_unavailable");
            }else if(path.equals("/csc/info") || path.equals("/csc/role") ||
                    path.equals("/csc/group") ||
                    path.equals("/csc/reset") || path.equals("/csc/normal/commit") ||
                    path.equals("/csc/commit") || path.equals("/csc/bonus/commit")){
                // The author response for these routes is empty. The ordinary
                // role fixture supplies real max-HP and servant templates;
                // LocalSave below emits the original CSC protobuf envelope.
                response=responseFixture(responses,"/combat/role/info");
            }
            boolean stageCombat=path.equals("/combat/mob/json") || path.equals("/combat/mob/info");
            if(stageCombat){
                if(!args.containsKey("instanceid"))
                    throw new BadRequest(400,"Missing encounter ID");
                long requested;
                try{requested=Long.parseLong(args.get("instanceid"));}
                catch(NumberFormatException ex){throw new BadRequest(400,"Invalid encounter ID");}
                if(requested!=StageCatalog.MAZE_TRIAL && !TutorialBattleFixtures.handles(requested) &&
                        !stages.supported(requested) && !dailyBattles.supports(requested) &&
                         !WeaponFurnace.contains(requested) && !BarrierLabyrinth.supports(requested) &&
                         !PreservedBattleCatalog.contains(requested) && !LocalActivityLab.contains(requested))
                    return error(422,"encounter_unavailable");
            }
            if (path.startsWith("/combat/") && args.containsKey("instanceid")) {
                JSONObject encounter = responses.optJSONObject(save.fixtureKey(path,args));
                if (encounter == null) encounter = responses.optJSONObject(path + "#" + args.get("instanceid"));
                if (encounter != null) response = encounter;
                else if(stageCombat)return error(422,"encounter_unavailable");
            }
            if (response == null && path.endsWith(".env")) response = responses.optJSONObject("*.env");
            if (response == null && path.endsWith(".mapping")) response = responses.optJSONObject("*.mapping");
            if (response == null || path.equals("/_catalog")) return error(404, "unknown_route");
            int status = response.optInt("status",200);
            byte[] content = response.has("base64") ? com.codex.witchweapon.host.Base64.decode(response.getString("base64"),0)
                : response.optString("body","").getBytes(StandardCharsets.UTF_8);
            if (status == 200 && response.has("base64")) {
                byte[] storyFixture=null;
                if(path.equals("/story/buy") || path.equals("/game/story/buy")){
                    JSONObject storyResponse=responseFixture(responses,"/story/get");
                    if(storyResponse==null || !storyResponse.has("base64"))
                        throw new IOException("Preserved story fixture missing");
                    storyFixture=com.codex.witchweapon.host.Base64.decode(
                        storyResponse.getString("base64"),0);
                }
                content=save.respond(path,args,content,responses.optJSONObject("_catalog"),storyFixture,
                    stages,dailyBattles,weaponFurnace);
            }
            if(status==200 && !response.has("base64") &&
               (path.equals("/csc/instance/json") || path.equals("/combat/mob/json") &&
                (Long.toString(StageCatalog.MAZE_TRIAL).equals(args.get("instanceid")) ||
                 BarrierLabyrinth.supports(Long.parseLong(args.get("instanceid"))))))
                content=save.mazeJson(content,responses.optJSONObject("_catalog"));
            return new Reply(status, response.optString("type","application/octet-stream"), content);
            }
    }
    private void handle(HttpExchange e) throws IOException {
        Reply reply;
        try { reply = resolve(e); }
        catch (BadRequest ex) {
            if ("/story/buy".equals(e.getRequestURI().getPath()) ||
                "/game/story/buy".equals(e.getRequestURI().getPath()))
                System.err.println("STORY_BUY_REJECT BAD_FORM_" + ex.status);
            reply = error(ex.status, "invalid_request");
        }
        catch (LocalActivityLab.Rejected ex) {
            System.err.println("LOCAL_ACTIVITY_REJECT "+ex.code);
            reply=error(422,"local_activity_"+ex.code.toLowerCase(java.util.Locale.ROOT));
        }
        catch (LocalSave.AdminMissing ex) { reply = error(404,"game_save_not_found"); }
        catch (AdminDataService.ActiveBattle ex) { reply = error(409,"active_battle"); }
        catch (LocalSave.AdminConflict ex) { reply = error(409,"save_conflict"); }
        catch (LocalSave.AdminValidation ex) { reply = error(422,"invalid_admin_patch"); }
        catch (LocalDaily.InvalidRequest ex) { reply = error(400,"invalid_daily_request"); }
        catch (LocalDaily.Conflict ex) { reply = error(409,"daily_conflict"); }
        catch (GuildStore.Invalid ex) { reply = error(400,"invalid_guild_request"); }
        catch (GuildStore.Forbidden ex) { reply = error(403,"guild_forbidden"); }
        catch (GuildStore.Conflict ex) { reply = error(409,"guild_conflict"); }
        catch (VipSystem.Invalid ex) { reply = error(400,"invalid_caph_request"); }
        catch (VipSystem.Conflict ex) { reply = error(409,"caph_reward_unavailable"); }
        catch (StaminaPurchase.Invalid ex) { reply = error(400,"invalid_stamina_request"); }
        catch (StaminaPurchase.Conflict ex) { reply = error(409,"stamina_purchase_unavailable"); }
        catch (PersistenceException ex) { System.err.println("SAVE_FAILURE " + ex.getClass().getSimpleName()); reply = error(500,"save_failed"); }
        catch (IOException ex) { System.err.println("REQUEST_REJECTED " + ex.getClass().getSimpleName()); reply = error(422,"action_rejected"); }
        catch (JSONException ex) { System.err.println("REQUEST_REJECTED " + ex.getClass().getSimpleName()); reply = error(422,"action_rejected"); }
        catch (Exception ex) { System.err.println("INTERNAL_ERROR " + ex.getClass().getSimpleName()); reply = error(500,"internal_error"); }
        // Slow/disconnected clients neither hold the save lock nor turn transport errors
        // into a second business-error response after a successful commit.
        try { send(e, reply.status, reply.type, reply.body); }
        finally { e.close(); }
    }
    public static void main(String[] args) throws Exception {
        Map<String,String> options = new HashMap<String,String>();
        for (int i=0; i<args.length; i+=2) {
            if (i+1>=args.length || !Arrays.asList("--port","--data-dir","--responses").contains(args[i]))
                throw new IllegalArgumentException("Options: --port --data-dir --responses");
            if (options.put(args[i],args[i+1])!=null) throw new IllegalArgumentException("Duplicate option");
        }
        int port = Integer.parseInt(options.containsKey("--port")?options.get("--port"):"19877");
        if (port<1 || port>65535) throw new IllegalArgumentException("Invalid port");
        if (!options.containsKey("--data-dir") || !options.containsKey("--responses")) throw new IllegalArgumentException("Explicit data and response paths required");
        String secret = System.getenv("WW_LEGACY_PROXY_SECRET");
        if (secret == null || secret.length() < 32 || secret.length() > 256)
            throw new IllegalArgumentException("WW_LEGACY_PROXY_SECRET must contain 32 to 256 characters");
        Path data = Paths.get(options.get("--data-dir")).toAbsolutePath().normalize();
        Files.createDirectories(data);
        // The explicitly configured root may be systemd's DynamicUser
        // StateDirectory alias. Pin its real directory once at startup;
        // administrator storage still rejects links beneath this root.
        data = data.toRealPath();
        final FileChannel lockChannel = FileChannel.open(data.resolve("server.lock"), StandardOpenOption.CREATE,StandardOpenOption.WRITE);
        final FileLock lock = lockChannel.tryLock();
        if (lock == null) { lockChannel.close(); throw new IOException("This save directory is already in use"); }
        final HttpServer server;
        final ExecutorService pool = new ThreadPoolExecutor(4,8,30,TimeUnit.SECONDS,new ArrayBlockingQueue<Runnable>(64),new ThreadPoolExecutor.AbortPolicy());
        try {
            final StandaloneServer host = new StandaloneServer(Paths.get(options.get("--responses")),data,port,secret);
            System.setProperty("sun.net.httpserver.maxReqTime","15");
            System.setProperty("sun.net.httpserver.maxRspTime","15");
            server = HttpServer.create(new InetSocketAddress(InetAddress.getByName("127.0.0.1"),port),32);
            server.createContext("/",new HttpHandler(){public void handle(HttpExchange e)throws IOException{host.handle(e);}});
            server.setExecutor(pool); server.start();
        } catch (Exception ex) { pool.shutdownNow(); lock.release(); lockChannel.close(); throw ex; }
        Runtime.getRuntime().addShutdownHook(new Thread(new Runnable(){public void run(){
            server.stop(1); pool.shutdownNow();
            try { lock.release(); lockChannel.close(); } catch(IOException ignored) {}
        }},"local-service-shutdown"));
        System.out.println("READY http://127.0.0.1:"+port+" account-isolated entries=241");
        System.out.flush();
        new CountDownLatch(1).await();
    }
}
