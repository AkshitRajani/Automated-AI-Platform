package com.lend.api;

import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.bind.annotation.RestController;

import com.lend.svc.LoanService;
import com.lend.svc.LoanServiceImpl;

@RestController
@RequestMapping("/loans")
public class LoanController {

    private final LoanService loans = new LoanServiceImpl();

    @GetMapping("/{id}")
    public String getLoan(String id) {
        return loans.findLoan(id);
    }

    @PostMapping
    public String createLoan(String payload) {
        return loans.createLoan(payload);
    }

    @DeleteMapping("/{id}")
    public void deleteLoan(String id) {
        loans.deleteLoan(id);
    }

    @RequestMapping(value = "/{id}", method = RequestMethod.PUT)
    public String updateLoan(String id, String payload) {
        return loans.updateLoan(id, payload);
    }

    @org.springframework.web.bind.annotation.GetMapping("/{id}/status")
    public String loanStatus(String id) {
        return loans.findLoan(id) == null ? "MISSING" : "ACTIVE";
    }
}
