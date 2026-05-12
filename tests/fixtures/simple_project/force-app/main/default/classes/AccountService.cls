public class AccountService {
    private static final String DEFAULT_STATUS = 'Active';

    public static List<Account> getActiveAccounts() {
        return [SELECT Id, Name, Status__c FROM Account WHERE Status__c = :DEFAULT_STATUS];
    }

    public static void updateAccountStatus(Id accountId, String newStatus) {
        Account acc = new Account(Id = accountId, Status__c = newStatus);
        update acc;
    }

    public static Boolean validateAccount(Account acc) {
        if (acc.Name == null || acc.Name == '') {
            return false;
        }
        return true;
    }
}
