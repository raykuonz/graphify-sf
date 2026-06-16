({
    doInit: function(component, event, helper) {
        var action = component.get("c.doThing");
        action.setCallback(this, function(response) {
            console.log(response.getReturnValue());
        });
        $A.enqueueAction(action);
    }
})
