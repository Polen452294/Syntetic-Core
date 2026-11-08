/* Apply WebKit's compiled Content Extensions to every GTK WebView, including popups.
 * No HTTP callbacks, request rewriting, or TLS inspection. Build with cc -shared -fPIC -ldl.
 * Only loaded into the dedicated browser attempt via its private environment.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

typedef uintptr_t Type;
extern const char *g_type_name(Type);
extern int g_main_context_iteration(void *, int);
extern void *g_file_new_for_path(const char *);
extern void g_object_unref(void *);
extern void *g_object_get_data(void *, const char *);
extern void g_object_set_data(void *, const char *, void *);

static void *filter;
static int completed;

static void *symbol(const char *name) {
    void *result = dlsym(RTLD_DEFAULT, name);
    if (!result) {
        fputs("QA native content blocker: required WebKitGTK API is unavailable\n", stderr);
        _exit(78);
    }
    return result;
}

static void saved(void *store, void *result, void *unused) {
    void *(*finish)(void *, void *, void **) =
        symbol(unused ? "webkit_user_content_filter_store_save_finish"
                      : "webkit_user_content_filter_store_save_from_file_finish");
    filter = finish(store, result, NULL);
    completed = 1;
}

static void attach(Type type, void *view) {
    const char *name = g_type_name(type);
    const char *rules = getenv("QA_WEBKIT_FILTER_RULES");
    if (!rules || !name || strcmp(name, "WebKitWebView"))
        return;
    if (!filter) {
        const char *cache = getenv("QA_WEBKIT_FILTER_CACHE");
        if (!cache)
            _exit(78);
        void *(*create_store)(const char *) = symbol("webkit_user_content_filter_store_new");
        void (*save)(void *, const char *, void *, void *, void (*)(void *, void *, void *), void *) =
            symbol("webkit_user_content_filter_store_save_from_file");
        void *store = create_store(cache);
        void *file = g_file_new_for_path(rules);
        save(store, "qa-offline", file, NULL, saved, NULL);
        while (!completed)
            g_main_context_iteration(NULL, 1);
        if (!filter) {
            /* Let the automation handshake finish, with all requests denied.
             * The supervisor then rejects the attempt and closes it normally. */
            const char *status = getenv("QA_WEBKIT_FILTER_STATUS");
            FILE *error = status ? fopen(status, "w") : NULL;
            if (error) {
                fputs("invalid-rules", error);
                fclose(error);
            }
            static const char deny[] =
                "[{\"trigger\":{\"url-filter\":\".*\"},\"action\":{\"type\":\"block\"}}]";
            void *(*bytes_new)(const void *, size_t) = symbol("g_bytes_new_static");
            void (*save_bytes)(void *, const char *, void *, void *,
                               void (*)(void *, void *, void *), void *) =
                symbol("webkit_user_content_filter_store_save");
            void *bytes = bytes_new(deny, sizeof(deny) - 1);
            completed = 0;
            save_bytes(store, "qa-deny-all", bytes, NULL, saved, (void *)1);
            while (!completed)
                g_main_context_iteration(NULL, 1);
            void (*bytes_unref)(void *) = symbol("g_bytes_unref");
            bytes_unref(bytes);
            if (!filter)
                _exit(78);
        }
        g_object_unref(file);
        g_object_unref(store);
    }
    void *(*manager_for_view)(void *) = symbol("webkit_web_view_get_user_content_manager");
    void *manager = manager_for_view(view);
    if (!g_object_get_data(manager, "qa-content-blocker")) {
        void (*add)(void *, void *) = symbol("webkit_user_content_manager_add_filter");
        add(manager, filter);
        g_object_set_data(manager, "qa-content-blocker", filter);
    }
}

void *g_object_new(Type type, const char *first, ...) {
    void *(*original)(Type, const char *, va_list) = dlsym(RTLD_NEXT, "g_object_new_valist");
    va_list args;
    va_start(args, first);
    void *object = original(type, first, args);
    va_end(args);
    attach(type, object);
    return object;
}

void *g_object_new_with_properties(Type type, unsigned count, const char **names, const void *values) {
    void *(*original)(Type, unsigned, const char **, const void *) =
        dlsym(RTLD_NEXT, "g_object_new_with_properties");
    void *object = original(type, count, names, values);
    attach(type, object);
    return object;
}
