/* Document API emulation for synthetic tests. This is not a native device backend. */
(config => {
    const marker = Symbol.for('synthetic-sessions.device-emulation.v1');
    if (globalThis[marker]) return;
    const makeNative = __NATIVE_FUNCTIONS__;
    const getter = (object, name, value) => {
        const descriptor = Object.getOwnPropertyDescriptor(object, name);
        Object.defineProperty(object, name, {
            configurable: descriptor?.configurable ?? true,
            enumerable: descriptor?.enumerable ?? true,
            get: makeNative(function () {
                if (descriptor?.get) Reflect.apply(descriptor.get, this, []);
                return value;
            }, 'get ' + name, descriptor?.get)
        });
    };
    const replace = (object, name, value, original = object[name]) => {
        const descriptor = Object.getOwnPropertyDescriptor(object, name);
        Object.defineProperty(object, name, {
            ...(descriptor ?? {configurable: true, writable: true}),
            value: makeNative(value, name, original)
        });
    };
    const nav = Object.getPrototypeOf(navigator);
    if (config.worker_user_agent != null)
        getter(nav, 'userAgent', config.worker_user_agent);
    if (config.max_touch_points != null)
        getter(nav, 'maxTouchPoints', config.max_touch_points);
    if (config.navigator_platform != null)
        getter(nav, 'platform', config.navigator_platform);
    const noise = index => {
        let n = (config.seed ^ Math.imul(index + 1, 2654435761)) >>> 0;
        n = Math.imul(n ^ (n >>> 16), 2246822507) >>> 0;
        return ((n >>> 8) / 16777216 - 0.5) * 1e-7;
    };
    if (config.hardware_concurrency != null)
        getter(nav, 'hardwareConcurrency', config.hardware_concurrency);
    if (config.device_memory != null && Object.getOwnPropertyDescriptor(nav, 'deviceMemory')?.get)
        getter(nav, 'deviceMemory', config.device_memory);
    if (config.battery && typeof nav.getBattery === 'function' && globalThis.BatteryManager) {
        const original = nav.getBattery;
        const states = new WeakMap(), promises = new WeakMap();
        const properties = ['charging', 'level', 'chargingTime', 'dischargingTime'];
        const epoch = config.battery_epoch_ms ?? Date.now();
        const reading = () => {
            const elapsed = Math.floor(Math.max(0, Date.now() - epoch) / 60000) * 60;
            const cfg = config.battery;
            const delta = elapsed / (cfg.charging ? cfg.charge_seconds : cfg.discharge_seconds);
            const level = Math.min(1, Math.max(0, cfg.level + (cfg.charging ? delta : -delta)));
            return {charging: cfg.charging, level,
                chargingTime: cfg.charging ? Math.round((1-level)*cfg.charge_seconds) : Infinity,
                dischargingTime: cfg.charging ? Infinity : Math.round(level*cfg.discharge_seconds)};
        };
        for (const name of properties) {
            const descriptor = Object.getOwnPropertyDescriptor(BatteryManager.prototype, name);
            if (!descriptor?.get) continue;
            Object.defineProperty(BatteryManager.prototype, name, {...descriptor,
                get: makeNative(function () {
                    const native = Reflect.apply(descriptor.get, this, []);
                    return states.get(this)?.[name] ?? native;
                }, 'get ' + name, descriptor.get)});
        }
        replace(nav, 'getBattery', function (...args) {
            // Native receiver, secure-context and Permissions Policy checks still run.
            const promise = Reflect.apply(original, this, args);
            const policy = document.permissionsPolicy ?? document.featurePolicy;
            if (policy?.features?.().includes('battery') && !policy.allowsFeature('battery'))
                return promise.then(() => {
                    throw new DOMException('Battery access is disallowed by Permissions Policy',
                        'NotAllowedError');
                });
            if (!promises.has(promise)) promises.set(promise, promise.then(battery => {
                if (states.has(battery)) return battery;
                states.set(battery, reading());
                for (const name of properties) battery.addEventListener(name.toLowerCase()+'change',
                    event => { if (event.isTrusted) event.stopImmediatePropagation(); }, true);
                setInterval(() => {
                    const previous = states.get(battery), next = reading();
                    states.set(battery, next);
                    for (const name of properties) if (previous[name] !== next[name])
                        battery.dispatchEvent(new Event(name.toLowerCase()+'change'));
                }, 1000);
                return battery;
            }));
            return promises.get(promise);
        });
    }
    if (config.privacy) {
        getter(nav, 'doNotTrack', config.privacy.do_not_track ? '1' : null);
        getter(nav, 'globalPrivacyControl', config.privacy.global_privacy_control);
    }
    if (config.webgl) {
        for (const name of ['WebGLRenderingContext', 'WebGL2RenderingContext']) {
            const proto = globalThis[name]?.prototype;
            if (!proto) continue;
            const original = proto.getParameter;
            replace(proto, 'getParameter', function (parameter) {
                // Preserve native receiver validation, errors and unsupported extensions.
                const value = Reflect.apply(original, this, [parameter]);
                if (this.isContextLost() || !this.getExtension('WEBGL_debug_renderer_info'))
                    return value;
                if (parameter === 37445) return config.webgl.vendor;
                if (parameter === 37446) return config.webgl.renderer;
                return value;
            });
        }
    }
    if (config.fonts) {
        const allowed = new Set(config.fonts.map(font => font.toLowerCase()));
        const generic = new Set(['serif', 'sans-serif', 'monospace', 'cursive', 'fantasy',
            'system-ui', 'ui-serif', 'ui-sans-serif', 'ui-monospace', 'emoji', 'math', 'fangsong']);
        const familyList = font => {
            const match = String(font).match(/(?:\d*\.?\d+)(?:px|pt|pc|em|rem|%)(?:\s*\/\s*[^\s]+)?\s+(.+)$/i);
            return match ? match[1].split(',').map(f => f.trim().replace(/^['"]|['"]$/g, '')) : [];
        };
        const supported = font => {
            const families = familyList(font);
            return !families.length || families.some(f => allowed.has(f.toLowerCase()) || generic.has(f.toLowerCase()));
        };
        const fontSet = globalThis.FontFaceSet?.prototype;
        if (fontSet) {
            const check = fontSet.check, load = fontSet.load;
            replace(fontSet, 'check', function (font, text) {
                const result = Reflect.apply(check, this, [font, text]);
                return supported(font) && result;
            });
            replace(fontSet, 'load', function (font, text) {
                const result = Reflect.apply(load, this, [font, text]);
                return supported(font) ? result : result.then(() => []);
            });
        }
        // Restrict canvas font selection without changing page CSS or installed fonts.
        for (const name of ['CanvasRenderingContext2D', 'OffscreenCanvasRenderingContext2D']) {
            const proto = globalThis[name]?.prototype;
            if (!proto) continue;
            const descriptor = Object.getOwnPropertyDescriptor(proto, 'font');
            if (!descriptor?.set || !descriptor.get) continue;
            Object.defineProperty(proto, 'font', {...descriptor, set: makeNative(function (value) {
                Reflect.apply(descriptor.set, this, [value]);
                const parsed = Reflect.apply(descriptor.get, this, []);
                if (!supported(parsed)) {
                    const families = familyList(parsed);
                    const prefix = parsed.slice(0, parsed.lastIndexOf(families[0]));
                    Reflect.apply(descriptor.set, this, [prefix.replace(/["']$/, '') + 'sans-serif']);
                }
            }, 'set font', descriptor.set)});
        }
    }
    if (config.audio) {
        for (const name of ['AudioContext', 'webkitAudioContext']) {
            const Original = globalThis[name];
            if (!Original) continue;
            const Wrapped = new Proxy(Original, {construct(target, args, newTarget) {
                const options = args[0] == null ? {} : args[0];
                return Reflect.construct(target, [{sampleRate: config.audio.sample_rate, ...options}], newTarget);
            }});
            replace(globalThis, name, Wrapped);
            const latency = Object.getOwnPropertyDescriptor(Original.prototype, 'outputLatency');
            Object.defineProperty(Original.prototype, 'outputLatency', {
                ...(latency ?? {configurable: true, enumerable: true}),
                get: makeNative(function () {
                    if (latency?.get) Reflect.apply(latency.get, this, []);
                    return config.audio.buffer_frames / this.sampleRate;
                }, 'get outputLatency', latency?.get)
            });
        }
        if (globalThis.AudioDestinationNode)
            getter(AudioDestinationNode.prototype, 'maxChannelCount', config.audio.max_channels);
        if (globalThis.AudioBuffer) {
            const channels = new WeakMap();
            const original = AudioBuffer.prototype.getChannelData;
            const read = function (channel) {
                const data = Reflect.apply(original, this, [channel]);
                let seen = channels.get(this);
                if (!seen) { seen = new Set(); channels.set(this, seen); }
                if (!seen.has(channel)) {
                    for (let i = 0; i < data.length; i++)
                        if (data[i] !== 0) data[i] += noise(i + channel * 8191);
                    seen.add(channel);
                }
                return data;
            };
            replace(AudioBuffer.prototype, 'getChannelData', read);
            const copy = AudioBuffer.prototype.copyFromChannel;
            if (copy) replace(AudioBuffer.prototype, 'copyFromChannel', function (destination, channel, offset) {
                Reflect.apply(read, this, [channel]);
                return Reflect.apply(copy, this, [destination, channel, offset]);
            });
        }
        if (globalThis.AnalyserNode) {
            for (const name of ['getFloatFrequencyData', 'getFloatTimeDomainData']) {
                const original = AnalyserNode.prototype[name];
                if (!original) continue;
                replace(AnalyserNode.prototype, name, function (values) {
                    const result = Reflect.apply(original, this, [values]);
                    for (let i = 0; i < values.length; i++)
                        if (Number.isFinite(values[i]) && values[i] !== 0) values[i] += noise(i);
                    return result;
                });
            }
        }
    }
    if (config.media && navigator.mediaDevices) {
        const proto = Object.getPrototypeOf(navigator.mediaDevices);
        const enumerate = proto.enumerateDevices;
        replace(proto, 'enumerateDevices', async function () {
            const native = await Reflect.apply(enumerate, this, []);
            const permissions = {};
            for (const [kind, permission] of [['audioinput', 'microphone'], ['videoinput', 'camera']]) {
                try { permissions[kind] = (await navigator.permissions.query({name: permission})).state === 'granted'; }
                catch { permissions[kind] = native.some(d => d.kind === kind && d.label); }
            }
            permissions.audiooutput = permissions.audioinput;
            const seen = new Set();
            return config.media.filter(device => {
                if (permissions[device.kind]) return true;
                if (seen.has(device.kind)) return false;
                seen.add(device.kind); return true;
            }).map(device => {
                const granted = permissions[device.kind];
                const result = Object.create(globalThis.MediaDeviceInfo?.prototype ?? Object.prototype);
                const data = {kind: device.kind, deviceId: granted ? device.device_id : '',
                    groupId: granted ? device.group_id : '', label: granted ? device.label : ''};
                for (const [key, value] of Object.entries(data)) getter(result, key, value);
                replace(result, 'toJSON', () => ({...data}));
                return result;
            });
        });
        // getUserMedia remains native: this list does not create physical streams.
    }
    if (config.voices && globalThis.speechSynthesis) {
        const proto = Object.getPrototypeOf(speechSynthesis), original = proto.getVoices;
        replace(proto, 'getVoices', function () {
            const voices = Reflect.apply(original, this, []);
            if (config.voices === 'none') return [];
            if (config.voice_platform_matches === false) return [];
            const filtered = voices.filter(voice =>
                (config.voices !== 'local' || voice.localService) &&
                (!config.voice_language || voice.lang.toLowerCase().split('-')[0] === config.voice_language));
            return filtered.filter((voice, index) => voice.default || ((index + config.seed) % 3 !== 0));
        });
    }
    if (config.sensor_readings && isSecureContext) {
        const permissions = config.grants.filter(g => g.origin === location.origin)
            .flatMap(g => g.permissions);
        const policy = document.permissionsPolicy ?? document.featurePolicy;
        const permitted = name => permissions.includes(name) && (!policy || policy.allowsFeature(name));
        const kinds = {Accelerometer: 'accelerometer', GravitySensor: 'gravity',
            LinearAccelerationSensor: 'linear-acceleration', Gyroscope: 'gyroscope',
            RelativeOrientationSensor: 'relative-orientation'};
        for (const [name, kind] of Object.entries(kinds)) {
            class EmulatedSensor extends EventTarget {
                #timer = null;
                #reading = false;
                #timestamp = null;
                #frequency;
                constructor(options = {}) {
                    super();
                    const frequency = options.frequency ?? 30;
                    if (!Number.isFinite(frequency) || frequency <= 0)
                        throw new TypeError('Sensor frequency must be positive');
                    this.#frequency = Math.min(frequency, 60);
                }
                get activated() { return this.#timer !== null; }
                get hasReading() { return this.#reading; }
                get timestamp() { return this.#timestamp; }
                get x() { return this.#reading ? config.sensor_readings[kind].xyz?.x ?? null : null; }
                get y() { return this.#reading ? config.sensor_readings[kind].xyz?.y ?? null : null; }
                get z() { return this.#reading ? config.sensor_readings[kind].xyz?.z ?? null : null; }
                get quaternion() {
                    return this.#reading && config.sensor_readings[kind].quaternion
                        ? new Float64Array(Object.values(config.sensor_readings[kind].quaternion)) : null;
                }
                #emit(type) {
                    const event = new Event(type);
                    this.dispatchEvent(event);
                    if (typeof this['on' + type] === 'function') this['on' + type](event);
                }
                start() {
                    if (this.activated) return;
                    const needed = kind === 'gyroscope' ? ['gyroscope']
                        : kind === 'relative-orientation' ? ['accelerometer', 'gyroscope'] : ['accelerometer'];
                    if (needed.some(permission => !permitted(permission))) {
                        queueMicrotask(() => {
                            const event = new Event('error');
                            Object.defineProperty(event, 'error', {value: new DOMException('Sensor permission denied', 'NotAllowedError')});
                            this.dispatchEvent(event);
                            if (typeof this.onerror === 'function') this.onerror(event);
                        });
                        return;
                    }
                    this.#timer = setInterval(() => {
                        if (document.visibilityState === 'hidden') return;
                        const first = !this.#reading;
                        this.#reading = true; this.#timestamp = performance.now();
                        if (first) this.#emit('activate');
                        this.#emit('reading');
                    }, 1000 / this.#frequency);
                }
                stop() {
                    clearInterval(this.#timer); this.#timer = null;
                    this.#reading = false; this.#timestamp = null;
                }
            }
            Object.defineProperty(EmulatedSensor, 'name', {value: name});
            for (const key of Object.getOwnPropertyNames(EmulatedSensor.prototype)) {
                if (key === 'constructor') continue;
                const descriptor = Object.getOwnPropertyDescriptor(EmulatedSensor.prototype, key);
                for (const slot of ['value', 'get', 'set']) {
                    if (typeof descriptor[slot] !== 'function') continue;
                    const label = slot === 'value' ? key : slot + ' ' + key;
                    descriptor[slot] = makeNative(descriptor[slot], label);
                }
                Object.defineProperty(EmulatedSensor.prototype, key, descriptor);
            }
            // Keep the implementation's prototype: these instances own private fields.
            const sensor = makeNative(EmulatedSensor, name);
            Object.defineProperty(EmulatedSensor.prototype, 'constructor', {value: sensor});
            Object.defineProperty(globalThis, name, {
                configurable: true, writable: true, value: sensor
            });
        }
    }
    Object.defineProperty(globalThis, marker, {value: true});
})(__DEVICE_EMULATION_CONFIG__);
