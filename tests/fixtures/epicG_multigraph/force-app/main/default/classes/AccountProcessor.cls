/**
 * AccountProcessor: queries AND dml-writes Account.
 * Used as the canonical same-direction parallel-relation test case for G3.
 */
public class AccountProcessor {
    public void process() {
        // queries relation
        List<Account> accs = [SELECT Id, Name FROM Account WHERE IsActive__c = true];
        for (Account acc : accs) {
            acc.Name = acc.Name + ' - processed';
        }
        // dml relation
        update accs;
    }
}
