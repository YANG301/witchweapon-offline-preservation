package com.codex.witchweapon;

import com.codex.witchweapon.host.AtomicFile;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;

/** Exercises rename/rollback/recovery paths, including directory-sync calls on POSIX. */
public final class AtomicFileSelfTest {
    private static void require(boolean ok,String message){if(!ok)throw new AssertionError(message);}
    private static byte[] bytes(String value){return value.getBytes(StandardCharsets.UTF_8);}
    public static void main(String[] args)throws Exception{
        if(args.length!=1)throw new IllegalArgumentException("Test directory required");
        File directory=new File(args[0]);
        if(!directory.isDirectory())throw new IllegalArgumentException("Test directory missing");
        File base=new File(directory,"save.json");
        AtomicFile file=new AtomicFile(base);
        FileOutputStream first=file.startWrite();
        first.write(bytes("old"));file.finishWrite(first);
        require(Arrays.equals(bytes("old"),file.readFully()),"Initial commit failed");
        FileOutputStream rejected=file.startWrite();
        rejected.write(bytes("discard"));file.failWrite(rejected);
        require(Arrays.equals(bytes("old"),file.readFully()),"Rollback lost old save");
        FileOutputStream interrupted=file.startWrite();
        interrupted.write(bytes("uncommitted"));interrupted.close();
        require(new File(base+".bak").isFile(),"Interrupted write lacked backup");
        require(Arrays.equals(bytes("old"),new AtomicFile(base).readFully()),
            "Interrupted write was not recovered");
        FileOutputStream last=file.startWrite();
        last.write(bytes("new"));file.finishWrite(last);
        require(Arrays.equals(bytes("new"),file.readFully()),"Final commit failed");
        require(!Files.exists(new File(base+".bak").toPath()),"Commit left a backup");
        System.out.println("ATOMIC_FILE_SELF_TEST_PASS");
    }
}
