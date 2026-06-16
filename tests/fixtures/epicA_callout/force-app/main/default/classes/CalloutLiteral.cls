public class CalloutLiteral {
    public static String fetchData() {
        HttpRequest req = new HttpRequest();
        req.setEndpoint('https://netsuite.example.com/v1/data');
        req.setMethod('GET');
        Http http = new Http();
        HttpResponse res = http.send(req);
        return res.getBody();
    }
}
