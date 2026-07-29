package com.lend.svc;

import org.springframework.jdbc.core.JdbcTemplate;

import software.amazon.awssdk.services.sns.SnsClient;
import software.amazon.awssdk.services.sns.model.PublishRequest;

public class AuditLog {

    private final JdbcTemplate jdbc = new JdbcTemplate();
    private final SnsClient sns = SnsClient.create();

    public void write(String event) {
        jdbc.update("INSERT INTO audit_trail (event_name) VALUES (?)", event);
        sns.publish(PublishRequest.builder()
                .topicArn("arn:aws:sns:us-east-1:000000000000:audit-events")
                .build());
    }
}
