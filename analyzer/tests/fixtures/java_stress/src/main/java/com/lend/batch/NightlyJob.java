package com.lend.batch;

import com.amazonaws.services.s3.AmazonS3;
import com.amazonaws.services.s3.AmazonS3ClientBuilder;

import software.amazon.awssdk.services.lambda.LambdaClient;
import software.amazon.awssdk.services.lambda.model.InvokeRequest;

import com.lend.svc.LoanService;
import com.lend.svc.LoanServiceImpl;

public class NightlyJob {

    private final AmazonS3 legacyS3 = AmazonS3ClientBuilder.defaultClient();
    private final LambdaClient lambda = LambdaClient.create();
    private final LoanService loans = new LoanServiceImpl();

    public void run() {
        String region = System.getenv("AWS_REGION");
        legacyS3.getObject("nightly-input", "batch/latest.csv");

        lambda.invoke(InvokeRequest.builder()
                .functionName("nightly-reconciler")
                .build());

        loans.findLoan("LN-0001");
    }
}
