public class EventPublisher {
    public static void publishOrder(String orderId) {
        Order_Event__e evt = new Order_Event__e(OrderId__c = orderId);
        EventBus.publish(new Order_Event__e(OrderId__c = orderId));
    }
}
