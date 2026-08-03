package io.setugateway;

/** Thrown when the gateway responds with a non-2xx status. */
public class SetuApiException extends RuntimeException {
    private final int statusCode;
    private final String body;

    public SetuApiException(int statusCode, String body) {
        super("Setu Gateway request failed (" + statusCode + "): " + body);
        this.statusCode = statusCode;
        this.body = body;
    }

    public int getStatusCode() {
        return statusCode;
    }

    public String getBody() {
        return body;
    }
}
