(() => {
    const marker = Symbol.for('synthetic-sessions.native-functions.v1');
    if (globalThis[marker]) return globalThis[marker];
    const sources = new WeakMap();
    const apply = Reflect.apply, construct = Reflect.construct;
    const descriptor = Object.getOwnPropertyDescriptor(Function.prototype, 'toString');
    const originalToString = descriptor.value;
    const makeNative = (implementation, name, original) => {
        let target = typeof original === 'function' ? original : implementation;
        if (typeof original !== 'function' && /^(get|set) /.test(name)) {
            // Synthetic getters also have no own prototype and cannot be constructed.
            target = {[name](...args) { return apply(implementation, this, args); }}[name];
            Object.defineProperty(target, 'length', {
                value: implementation.length, configurable: true
            });
        }
        if (target === implementation && target.name !== name)
            Object.defineProperty(target, 'name', {value: name, configurable: true});
        // A native target preserves its prototype, arity and constructibility.
        const wrapped = new Proxy(target, {
            apply(_target, receiver, args) { return apply(implementation, receiver, args); },
            construct(_target, args, newTarget) {
                return construct(implementation, args, newTarget);
            }
        });
        sources.set(wrapped, `function ${name}() { [native code] }`);
        return wrapped;
    };
    const toString = new Proxy(originalToString, {apply(target, receiver, args) {
        return sources.has(receiver) ? sources.get(receiver) : apply(target, receiver, args);
    }});
    sources.set(toString, apply(originalToString, originalToString, []));
    Object.defineProperty(Function.prototype, 'toString', {...descriptor, value: toString});
    Object.defineProperty(globalThis, marker, {value: makeNative});
    return makeNative;
})()
