package com.lend.svc;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.util.ArrayList;
import java.util.List;

import software.amazon.awssdk.core.sync.RequestBody;
import software.amazon.awssdk.services.dynamodb.DynamoDbClient;
import software.amazon.awssdk.services.dynamodb.model.PutItemRequest;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.GetObjectRequest;
import software.amazon.awssdk.services.s3.model.PutObjectRequest;
import software.amazon.awssdk.services.sfn.SfnClient;
import software.amazon.awssdk.services.sfn.model.StartExecutionRequest;

public class LoanServiceImpl implements LoanService {

    private static final String LOAN_QUERY =
        "SELECT l.loan_id FROM loans l WHERE l.loan_id = ?";

    private final S3Client s3 = S3Client.create();
    private final SfnClient stepFunctions = SfnClient.create();
    private final DynamoDbClient dynamo = DynamoDbClient.create();

    @Override
    public String findLoan(String id) {
        try {
            var conn = DriverManager.getConnection(System.getenv("LOAN_DB_URL"));
            PreparedStatement ps = conn.prepareStatement(
                "SELECT l.loan_id, b.upb_amt, r.rate_pct FROM loans l "
                + "JOIN loan_balances b ON l.loan_id = b.loan_id "
                + "LEFT JOIN rate_history r ON l.loan_id = r.loan_id "
                + "WHERE l.loan_id = ?");
            ps.setString(1, id);
            ResultSet rs = ps.executeQuery();
            return rs.next() ? rs.getString(1) : null;
        } catch (Exception e) {
            return null;
        }
    }

    @Override
    public String createLoan(String payload) {
        try {
            Connection conn = DriverManager.getConnection(System.getenv("LOAN_DB_URL"));
            PreparedStatement ps = conn.prepareStatement(
                "INSERT INTO loans (loan_id, payload) VALUES (?, ?)");
            ps.setString(1, payload);
            ps.executeUpdate();

            s3.putObject(PutObjectRequest.builder()
                    .bucket("loan-archive")
                    .key("loans/incoming.json")
                    .build(),
                RequestBody.fromString(payload));

            stepFunctions.startExecution(StartExecutionRequest.builder()
                    .stateMachineArn("arn:aws:states:us-east-1:000000000000:stateMachine:loan-boarding")
                    .build());

            dynamo.putItem(PutItemRequest.builder()
                    .tableName("loan-status-tracker")
                    .build());

            AuditLog audit = new AuditLog();
            audit.write("loan-created");
            double rate = RateCalculator.calc(0.0625, 30);
            return payload + ":" + rate;
        } catch (Exception e) {
            return null;
        }
    }

    @Override
    public void deleteLoan(String id) {
        try {
            Connection conn = DriverManager.getConnection(System.getenv("LOAN_DB_URL"));
            conn.createStatement().executeUpdate(
                "DELETE FROM loans WHERE loan_id = '" + id + "'");
        } catch (Exception ignored) {
        }
    }

    @Override
    public String updateLoan(String id, String payload) {
        try {
            Connection conn = DriverManager.getConnection(System.getenv("LOAN_DB_URL"));
            // constant-reference SQL: a known slice-1 miss (arg is a name, not a literal)
            PreparedStatement ps = conn.prepareStatement(LOAN_QUERY);
            ps.setString(1, id);
            ps.executeQuery();

            byte[] archived = s3.getObject(GetObjectRequest.builder()
                    .bucket("loan-archive")
                    .key("loans/" + id + ".json")
                    .build()).readAllBytes();

            List<String> tags = new ArrayList<>();
            tags.stream().map(t -> t.trim()).forEach(t -> tag(t));
            return new String(archived);
        } catch (Exception e) {
            return null;
        }
    }

    private void tag(String value) {
    }
}
