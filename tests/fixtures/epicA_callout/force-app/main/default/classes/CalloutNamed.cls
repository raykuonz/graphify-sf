public class CalloutNamed {
    public static String fetchOrders() {
        HttpRequest req = new HttpRequest();
        req.setEndpoint('callout:My_NC/orders');
        req.setMethod('GET');
        Http http = new Http();
        HttpResponse res = http.send(req);
        return res.getBody();
    }
}
