import { LightningElement } from 'lwc';
import NAME_FIELD from '@salesforce/schema/Account.Name';
import LABEL_GREETING from '@salesforce/label/c.Greeting';
import MY_RESOURCE from '@salesforce/resourceUrl/MyResource';
import doThing from '@salesforce/apex/MyService.doThing';

export default class SchemaLwc extends LightningElement {
    nameField = NAME_FIELD;
    label = LABEL_GREETING;
    resource = MY_RESOURCE;

    handleClick() {
        doThing();
    }
}
