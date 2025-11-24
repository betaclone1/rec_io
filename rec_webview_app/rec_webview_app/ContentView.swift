import SwiftUI
import WebKit
import SafariServices

struct WebView: UIViewRepresentable {
    let url: URL

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.allowsInlineMediaPlayback = true
        configuration.mediaTypesRequiringUserActionForPlayback = []
        
        // Configure for HTTP access
        configuration.websiteDataStore = WKWebsiteDataStore.default()
        configuration.preferences.javaScriptEnabled = true
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = true
        
        // Additional webview input compatibility settings
        configuration.suppressesIncrementalRendering = false
        configuration.allowsAirPlayForMediaPlayback = false
        
        let webView = WKWebView(frame: .zero, configuration: configuration)
        // REMOVED: Cache clearing code that was wiping authentication cookies
        webView.navigationDelegate = context.coordinator
        webView.scrollView.bounces = false
        webView.scrollView.isScrollEnabled = false
        webView.translatesAutoresizingMaskIntoConstraints = false
        
        // Webview input compatibility fixes
        webView.isOpaque = false
        webView.backgroundColor = UIColor.black
        webView.scrollView.keyboardDismissMode = .onDrag
        webView.allowsBackForwardNavigationGestures = false
        
        // Enable text selection and interaction
        webView.allowsLinkPreview = false
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        webView.scrollView.contentInset = .zero
        webView.scrollView.scrollIndicatorInsets = .zero
        
        print("🔧 WebView configured for URL: \(url.absoluteString)")
        return webView
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {
        var request = URLRequest(url: url)
        // CHANGED: Allow caching to preserve authentication cookies
        request.cachePolicy = .useProtocolCachePolicy
        uiView.load(request)
    }

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    class Coordinator: NSObject, WKNavigationDelegate {
        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            print("❌ Navigation error: \(error.localizedDescription)")
            print("❌ Error code: \((error as NSError).code)")
            print("❌ Error domain: \((error as NSError).domain)")
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            print("❌ Provisional navigation error: \(error.localizedDescription)")
            print("❌ Error code: \((error as NSError).code)")
            print("❌ Error domain: \((error as NSError).domain)")
            
            // Try to handle ATS errors specifically
            let nsError = error as NSError
            if nsError.domain == NSURLErrorDomain && nsError.code == NSURLErrorAppTransportSecurityRequiresSecureConnection {
                print("🔧 ATS Error detected - showing error message")
                // Don't retry automatically to avoid infinite loop
            }
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            print("✅ Finished loading URL: \(webView.url?.absoluteString ?? "unknown")")
            
            // Inject CSS/JS to remove extra bottom padding inside the page so the in-page menu can sit at the true bottom.
            let js = """
            (function() {
                try {
                    var html = document.documentElement;
                    var body = document.body;
                    if (!html || !body) { return; }
                    html.style.margin = '0';
                    html.style.padding = '0';
                    body.style.margin = '0';
                    body.style.paddingBottom = '0';
                    body.style.marginBottom = '0';
                } catch (e) {
                    console.log('rec_webview_app: CSS inject error', e);
                }
            })();
            """
            webView.evaluateJavaScript(js) { result, error in
                if let error = error {
                    print("❌ JS injection error: \(error.localizedDescription)")
                } else {
                    print("🔧 JS injection applied to remove bottom padding.")
                }
            }
        }
        
        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            print("🔧 Navigation decision for: \(navigationAction.request.url?.absoluteString ?? "unknown")")
            decisionHandler(.allow)
        }
    }
}

struct ContentView: View {
    var body: some View {
        WebView(url: resolvedURL).ignoresSafeArea(.container, edges: [.bottom]).background(Color.black)
    }

    private var resolvedURL: URL {
        let urlString: String
        switch UIDevice.current.userInterfaceIdiom {
        case .pad:
            urlString = "https://rec-io.com/"
        case .phone:
            urlString = "https://rec-io.com/"
        default:
            urlString = "https://rec-io.com/"
        }
        print("🔧 Attempting to load URL: \(urlString)")
        return URL(string: urlString)!
    }
}
