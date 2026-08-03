package io.setugateway;

/** A single chat message, matching the OpenAI-compatible shape. */
public class Message {
    public String role;
    public String content;

    public Message() {
    }

    public Message(String role, String content) {
        this.role = role;
        this.content = content;
    }
}
