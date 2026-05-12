import { LightningElement, api } from 'lwc';
import getActiveAccounts from '@salesforce/apex/AccountService.getActiveAccounts';

export default class AccountCard extends LightningElement {
    @api recordId;
    accounts = [];

    connectedCallback() {
        this.loadAccounts();
    }

    async loadAccounts() {
        try {
            this.accounts = await getActiveAccounts();
        } catch (error) {
            console.error('Error loading accounts:', error);
        }
    }
}
