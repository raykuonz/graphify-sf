import { LightningElement } from 'lwc';

export default class CreateAccount extends LightningElement {
    handleSave() {
        this.dispatchEvent(new CustomEvent('save'));
    }
}
