package com.demo.svc;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;

import software.amazon.awssdk.core.sync.RequestBody;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.PutObjectRequest;
import software.amazon.awssdk.services.lambda.LambdaClient;
import software.amazon.awssdk.services.lambda.model.InvokeRequest;

public class OrderService {

    private final S3Client s3 = S3Client.create();
    private final LambdaClient lambdaClient = LambdaClient.create();

    public String findOrder(String id) throws Exception {
        String dbHost = System.getenv("DB_HOST");
        Connection conn = DriverManager.getConnection(dbHost);
        PreparedStatement ps = conn.prepareStatement(
            "SELECT o.order_id, c.customer_name FROM orders o JOIN customers c ON o.customer_id = c.customer_id WHERE o.order_id = ?");
        ps.setString(1, id);
        ResultSet rs = ps.executeQuery();
        return rs.next() ? rs.getString(1) : null;
    }

    public String createOrder(String payload) throws Exception {
        Connection conn = DriverManager.getConnection(System.getenv("DB_HOST"));
        PreparedStatement ps = conn.prepareStatement(
            "INSERT INTO orders (payload) VALUES (?)");
        ps.setString(1, payload);
        ps.executeUpdate();

        s3.putObject(PutObjectRequest.builder()
                .bucket("order-archive")
                .key("orders/latest.json")
                .build(),
            RequestBody.fromString(payload));

        lambdaClient.invoke(InvokeRequest.builder()
                .functionName("order-notifier")
                .build());

        return archiveKey(payload);
    }

    private String archiveKey(String payload) {
        return "orders/" + payload.hashCode();
    }
}
