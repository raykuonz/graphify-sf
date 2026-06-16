trigger OrderEventTrigger on Order_Event__e (after insert) {
    for (Order_Event__e evt : Trigger.new) {
        System.debug('Order event: ' + evt.OrderId__c);
    }
}
