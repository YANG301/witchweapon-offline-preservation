package com.codex.witchweapon.host;

import java.io.*;
import java.nio.channels.FileChannel;
import java.nio.file.*;

/** Desktop storage adapter, not an Android API stub. Backup wins after interrupted writes. */
public final class AtomicFile {
    private final File base, backup, pending;
    public AtomicFile(File base) {
        this.base = base;
        this.backup = new File(base.getPath() + ".bak");
        this.pending = new File(base.getPath() + ".new");
    }
    public File getBaseFile() { return base; }
    private static void move(File from, File to) throws IOException {
        // Refuse a filesystem without same-volume atomic replace instead of claiming durability.
        Files.move(from.toPath(), to.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
    }
    private void syncDirectory() throws IOException {
        Path directory=base.toPath().toAbsolutePath().getParent();
        // POSIX file-system rename/delete durability requires syncing the
        // containing directory. Windows directory channels are unsupported.
        if(!Files.getFileStore(directory).supportsFileAttributeView("posix"))return;
        try(FileChannel channel=FileChannel.open(directory,StandardOpenOption.READ)){
            channel.force(true);
        }
    }
    public byte[] readFully() throws IOException {
        try {
            if (backup.exists()) { move(backup, base); syncDirectory(); }
            return Files.readAllBytes(base.toPath());
        } catch (IOException e) { throw new PersistenceException("Cannot read local save", e); }
    }
    public FileOutputStream startWrite() throws IOException {
        try {
            if (pending.exists() && !pending.isFile()) throw new IOException("Pending save path is not a file");
            if (backup.exists()) { move(backup, base); syncDirectory(); }
            if (base.exists()) { move(base, backup); syncDirectory(); }
            try { return new FileOutputStream(pending); }
            catch (IOException e) { if (backup.exists()) { move(backup, base); syncDirectory(); } throw e; }
        } catch (IOException e) { throw new PersistenceException("Cannot begin local save write", e); }
    }
    public void finishWrite(FileOutputStream stream) throws IOException {
        try {
            stream.flush(); stream.getFD().sync(); stream.close();
            move(pending, base);
            // If this sync fails, .bak still exists and failWrite can restore it.
            syncDirectory();
            Files.deleteIfExists(backup.toPath());
            // Once .bak has been removed, the new base is authoritative in this
            // process. Report a late sync failure without lying to LocalSave
            // that a successful commit can still be rolled back.
            try { syncDirectory(); }
            catch (IOException e) { System.err.println("SAVE_DIRECTORY_SYNC_FAILED"); }
        } catch (IOException e) { throw new PersistenceException("Cannot commit local save", e); }
    }
    public void failWrite(FileOutputStream stream) throws IOException {
        IOException failure = null;
        try { stream.close(); } catch (IOException e) { failure = e; }
        try {
            Files.deleteIfExists(pending.toPath());
            if (backup.exists()) move(backup, base);
            syncDirectory();
        } catch (IOException e) { if (failure == null) failure = e; else failure.addSuppressed(e); }
        if (failure != null) throw new PersistenceException("Cannot roll back local save", failure);
    }
}
