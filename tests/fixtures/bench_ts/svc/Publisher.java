public class Publisher {
    private String getTenantId() {
        return "publisher";
    }

    public void publish() {
        String own = getTenantId();
        String ctx = TenantContext.getTenantId();
    }
}
