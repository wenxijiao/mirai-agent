import java.util.concurrent.CountDownLatch;

/**
 * Standalone entry: run this class from your IDE, or {@code mvn exec:java} with this as mainClass.
 * Delete this class when you integrate {@link MiraiSetup#initMirai()} into your application's main.
 */
public class MiraiEdgeMain {

    public static void main(String[] args) throws InterruptedException {
        MiraiSetup.initMirai();
        System.err.println("Mirai edge running. Press Ctrl+C to exit.");
        new CountDownLatch(1).await();
    }
}
