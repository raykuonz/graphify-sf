public class AccountTriggerHandler {
    public static void handleBeforeInsert(List<Account> newAccounts) {
        for (Account acc : newAccounts) {
            if (!AccountService.validateAccount(acc)) {
                acc.addError('Account validation failed');
            }
        }
    }

    public static void handleAfterUpdate(Map<Id, Account> newMap, Map<Id, Account> oldMap) {
        List<Account> changed = new List<Account>();
        for (Id accId : newMap.keySet()) {
            if (newMap.get(accId).Status__c != oldMap.get(accId).Status__c) {
                changed.add(newMap.get(accId));
            }
        }
        if (!changed.isEmpty()) {
            AccountService.updateAccountStatus(changed[0].Id, 'Updated');
        }
    }
}
