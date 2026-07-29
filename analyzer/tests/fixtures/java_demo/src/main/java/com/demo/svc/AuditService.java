package com.demo.svc;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.Statement;

public class AuditService {

    public void record(String event) throws Exception {
        Connection conn = DriverManager.getConnection(System.getenv("AUDIT_DB_URL"));
        Statement st = conn.createStatement();
        st.executeUpdate("INSERT INTO audit_log (event) VALUES ('" + event + "')");
    }
}
