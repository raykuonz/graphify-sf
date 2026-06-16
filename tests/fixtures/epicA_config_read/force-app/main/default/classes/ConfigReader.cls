public class ConfigReader {
    public static String getConfig() {
        Integration_Config__mdt cfg = Integration_Config__mdt.getInstance('NS');
        return cfg != null ? (String) cfg.get('Value__c') : null;
    }
}
