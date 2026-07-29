package com.lend.api;

import javax.ws.rs.GET;
import javax.ws.rs.POST;
import javax.ws.rs.Path;

import com.lend.svc.RateCalculator;

@Path("/reports")
public class ReportResource {

    @GET
    @Path("/daily")
    public String dailyReport() {
        return "rate=" + RateCalculator.calc(0.065);
    }

    @POST
    @Path("/regenerate")
    public String regenerate(String body) {
        return "queued:" + body.length();
    }
}
