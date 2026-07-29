package com.lend.svc;

public interface LoanService {
    String findLoan(String id);
    String createLoan(String payload);
    void deleteLoan(String id);
    String updateLoan(String id, String payload);
}
