public class MyCtrl {
    @AuraEnabled
    public static String doThing() {
        return 'result';
    }
}
