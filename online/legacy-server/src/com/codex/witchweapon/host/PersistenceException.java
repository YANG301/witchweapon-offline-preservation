package com.codex.witchweapon.host;

import java.io.IOException;

/** A storage failure is never reported as a successful game action. */
public final class PersistenceException extends IOException {
    public PersistenceException(String message, Throwable cause) { super(message, cause); }
}
