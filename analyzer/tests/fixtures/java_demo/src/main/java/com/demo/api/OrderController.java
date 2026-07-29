package com.demo.api;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.demo.svc.AuditService;
import com.demo.svc.OrderService;

@RestController
@RequestMapping("/api")
public class OrderController {

    private final OrderService orders = new OrderService();
    private final AuditService audit = new AuditService();

    @GetMapping("/orders/{id}")
    public String getOrder(String id) {
        return orders.findOrder(id);
    }

    @PostMapping("/orders")
    public String createOrder(@RequestBody String payload) {
        String created = orders.createOrder(payload);
        audit.record("order-created");
        return created;
    }
}
