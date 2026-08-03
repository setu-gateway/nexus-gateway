package io.setugateway;

/** Thrown when the gateway can't be reached at all. */
public class SetuConnectionException extends RuntimeException {
    public SetuConnectionException(String baseUrl, Throwable cause) {
        super("Could not reach Setu Gateway at " + baseUrl, cause);
    }
}
