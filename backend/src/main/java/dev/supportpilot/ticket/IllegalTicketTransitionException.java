package dev.supportpilot.ticket;

public class IllegalTicketTransitionException extends RuntimeException {
    public IllegalTicketTransitionException(TicketStatus from, TicketStatus to) {
        super("不允许将工单从 " + from + " 流转到 " + to);
    }
}
