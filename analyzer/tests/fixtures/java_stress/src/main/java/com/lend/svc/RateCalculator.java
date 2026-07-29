package com.lend.svc;

public class RateCalculator {

    public enum RateTier {
        PRIME, SUBPRIME;

        public String label() {
            return name().toLowerCase();
        }
    }

    public static double calc(double base) {
        return calc(base, 30);
    }

    public static double calc(double base, int termYears) {
        return base + (termYears > 15 ? 0.005 : 0.0);
    }
}
