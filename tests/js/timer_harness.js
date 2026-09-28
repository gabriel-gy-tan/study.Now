/* Behavioural harness for static/timer.js.
 *
 * Builds a minimal DOM stub, loads the real timer.js, and drives it with a
 * fake clock so behaviour can be checked rather than inferred from strings.
 *
 * Run directly:  node tests/js/timer_harness.js
 * Pytest runs it too, through the js_harness fixture in tests/conftest.py,
 * which skips rather than fails when node is not installed.
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const TIMER = path.join(__dirname, "..", "..", "static", "timer.js");

let failures = 0;
function check(name, cond, detail) {
    if (cond) {
        console.log("PASS  " + name);
    } else {
        failures++;
        console.log("FAIL  " + name + (detail ? "  -> " + detail : ""));
    }
}

/* The fullscreen APIs are allowed to refuse. A refusal that timer.js forgets
   to catch would surface as an unhandled rejection in a browser; recording it
   here keeps that from passing as a green run. */
const unhandled = [];
process.on("unhandledRejection", (err) => unhandled.push(err));

/* A class list that actually tracks state. The fullscreen code reads
   `document.body.classList.contains(...)` and calls `toggle(name, force)`,
   so a stub that always returns false would let every check pass. */
function makeClassList(initial) {
    const set = new Set(initial || []);
    return {
        add(...names) { names.forEach((n) => set.add(n)); },
        remove(...names) { names.forEach((n) => set.delete(n)); },
        contains(name) { return set.has(name); },
        toggle(name, force) {
            const want = force === undefined ? !set.has(name) : Boolean(force);
            if (want) { set.add(name); } else { set.delete(name); }
            return want;
        },
        toString() { return Array.from(set).join(" "); },
    };
}

/* ---- tiny DOM stub -------------------------------------------------- */
function makeEl(tag) {
    return {
        tagName: tag,
        attrs: {},
        _text: "",
        hidden: false,
        disabled: false,
        options: [],
        selectedIndex: 0,
        listeners: {},
        classList: makeClassList(),
        style: {},
        getAttribute(k) { return this.attrs[k] === undefined ? null : this.attrs[k]; },
        setAttribute(k, v) { this.attrs[k] = String(v); },
        removeAttribute(k) { delete this.attrs[k]; },
        hasAttribute(k) { return this.attrs[k] !== undefined; },
        addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); },
        closest() { return null; },
        focus() {},
        remove() {},
        isConnected: true,
        get textContent() { return this._text; },
        set textContent(v) {
            if (process.env.TRACE && this.tagName === tag) {
                console.log("   TRACE " + tag + " <- " + JSON.stringify(v));
            }
            this._text = v;
        },
        querySelector() { return null; },
        querySelectorAll() { return []; },
    };
}

function buildDom(userId) {
    const card = makeEl("section");
    card.setAttribute("data-user-id", userId);

    const readout = makeEl("output");
    const readoutLive = makeEl("p");
    const stateLabel = makeEl("span");
    const subjectLabel = makeEl("span");
    const lock = makeEl("div");
    const lockText = makeEl("span");
    const finish = makeEl("button");
    const finishLabel = makeEl("span");
    const start = makeEl("button");
    const pause = makeEl("button");
    const resume = makeEl("button");
    const discard = makeEl("button");
    const fullscreen = makeEl("button");
    const fullscreenLabel = makeEl("span");
    fullscreen.setAttribute("aria-pressed", "false");
    /* Mirrors the initial markup: the first click has to read as an entry. */
    fullscreenLabel.textContent = "Full screen";

    const options = [
        { value: "", text: "Choose a subject", disabled: true },
        { value: "3", text: "Mathematics" },
        { value: "5", text: "Physics" },
    ];

    const select = makeEl("select");
    select.options = options;
    select.value = "";
    select.addAttribute = select.addAttribute || function () {};

    card.querySelector = function (sel) {
        const map = {
            "[data-timer-readout]": readout,
            "[data-timer-readout-live]": readoutLive,
            "[data-timer-state]": stateLabel,
            "[data-timer-subject]": subjectLabel,
            "[data-timer-lock]": lock,
            "[data-timer-lock-text]": lockText,
            "[data-timer-finish]": finish,
            "[data-timer-finish-label]": finishLabel,
            "[data-timer-fullscreen]": fullscreen,
            "[data-timer-fullscreen-label]": fullscreenLabel,
        };
        return map[sel] || null;
    };

    const byId = { "#category": select };
    const byData = {
        "[data-timer-start]": start,
        "[data-timer-pause]": pause,
        "[data-timer-resume]": resume,
        "[data-timer-discard]": discard,
        "[data-timer-finish]": finish,
        "[data-timer-fullscreen]": fullscreen,
    };

    const meta = makeEl("meta");
    meta.setAttribute("content", "test-csrf");

    const store = {};
    const posts = [];
    const flags = { failSelect: false, failFullscreen: false, failExitFullscreen: false };
    let intervals = 0;
    let intervalFn = null;
    let clock = 1700000000000;

    const docListeners = {};
    const document = {
        title: "Study",
        hidden: false,
        /* Mirrors the browser: null when nothing is genuinely fullscreen. */
        fullscreenElement: null,
        body: { classList: makeClassList() },
        querySelector(s) {
            if (s === 'meta[name="csrf-token"]') return meta;
            if (s === "[data-timer-card]") return card;
            if (s === "#category") return select;
            return byData[s] || null;
        },
        addEventListener(t, f) { (docListeners[t] = docListeners[t] || []).push(f); },
        removeEventListener() {},
        exitFullscreen() {
            if (flags.failExitFullscreen) {
                return Promise.reject(new Error("refused"));
            }
            document.fullscreenElement = null;
            return Promise.resolve();
        },
    };

    /* Recorded so Escape and a native fullscreen exit can be driven from a
       check, rather than assumed to work. */
    function dispatchDoc(type, event) {
        (docListeners[type] || []).forEach((f) => f(event || { key: type }));
    }

    /* The real API exists and may be refused; timer.js must swallow that. */
    card.requestFullscreen = function () {
        if (flags.failFullscreen) {
            return Promise.reject(new Error("not allowed"));
        }
        document.fullscreenElement = card;
        return Promise.resolve();
    };

    const window = {
        localStorage: {
            getItem: (k) => (k in store ? store[k] : null),
            setItem: (k, v) => { store[k] = String(v); },
            removeItem: (k) => { delete store[k]; },
        },
        setInterval(fn) { intervals++; intervalFn = fn; return intervals; },
        clearInterval() { intervals = 0; intervalFn = null; },
        addEventListener() {},
        confirm: () => true,
        fetch: null,
    };
    window.window = window;

    const ctx = {
        document,
        window,
        console,
        Date: { now: () => clock },
        JSON,
        String,
        Number,
        Math,
        Boolean,
        Object,
        Array,
        Error,
        setTimeout,
        fetch(url, opts) {
            posts.push({ url, body: JSON.parse(opts.body), headers: opts.headers });
            if (url === "/select-category" && flags.failSelect) {
                return Promise.resolve({ ok: false, status: 403 });
            }
            return Promise.resolve({ ok: true, status: 200 });
        },
    };
    ctx.globalThis = ctx;

    /* advance the clock, then emulate one 250ms setInterval callback */
    function tick(ms) {
        clock += ms;
        if (intervalFn) {
            intervalFn();
        }
    }

    return {
        card, select, start, pause, resume, discard, finish, finishLabel,
        lock, lockText, readout, readoutLive, stateLabel, subjectLabel,
        fullscreen, fullscreenLabel, dispatchDoc,
        options, store, posts, window, document, ctx, tick, flags,
        get intervals() { return intervals; },
        setClock: (t) => { clock = t; },
        clockNow: () => clock,
        /* flush the whole fetch -> then -> catch promise chain */
        awaitMicro: () => new Promise((r) => setTimeout(r, 10)),
    };
}

function load(dom) {
    const code = fs.readFileSync(TIMER, "utf8");
    vm.createContext(dom.ctx);
    vm.runInContext(code, dom.ctx);
}

function fire(el, type) {
    (el.listeners[type] || []).forEach((f) => f({ target: el, preventDefault() {} }));
}

(async function main() {
    /* ---- 1. subject stays locked while running ---- */
    {
        const d = buildDom("u1");
        load(d);
        d.select.value = "3";
        fire(d.select, "change");
        await new Promise((r) => setTimeout(r, 0));

        fire(d.start, "click");
        check("start begins a run", d.card.getAttribute("data-state") === "running",
              d.card.getAttribute("data-state"));
        check("select is disabled WHILE RUNNING (elapsed is still 0)", d.select.disabled === true,
              "select.disabled=" + d.select.disabled);
        check("lock banner is hidden while running", d.lock.hidden === true,
              "lock.hidden=" + d.lock.hidden);
        check("finish is unavailable at exactly zero", d.finish.disabled === true,
              "finish.disabled=" + d.finish.disabled);

        d.tick(1000);
        check("finish becomes available once time passes", d.finish.disabled === false,
              "finish.disabled=" + d.finish.disabled);
        fire(d.finish, "click");
        await new Promise((r) => setTimeout(r, 0));
    }

    /* ---- 2. a change while locked is reverted, server not re-told ---- */
    {
        const d = buildDom("u1");
        load(d);
        d.select.value = "3";
        fire(d.select, "change");
        await new Promise((r) => setTimeout(r, 0));
        const postsBefore = d.posts.length;

        fire(d.start, "click");
        /* simulate the user scrolling the wheel over the focused select */
        d.select.value = "5";
        fire(d.select, "change");

        check("locked change is reverted to the confirmed subject", d.select.value === "3",
              "value=" + d.select.value);
        check("locked change does not POST a new category", d.posts.length === postsBefore,
              "posts=" + (d.posts.length - postsBefore));
        check("locked change explains itself", /locked/i.test(d.lockText.textContent),
              JSON.stringify(d.lockText.textContent));
    }

    /* ---- 3. >24h is refused client-side with a message ---- */
    {
        const d = buildDom("u1");
        load(d);
        d.select.value = "3";
        fire(d.select, "change");
        await new Promise((r) => setTimeout(r, 0));
        fire(d.start, "click");
        d.tick(8 * 24 * 3600 * 1000);
        fire(d.finish, "click");
        await new Promise((r) => setTimeout(r, 0));
        const finishPosts = d.posts.filter((p) => p.url === "/finish");
        check("an 8-day session never reaches /finish", finishPosts.length === 0,
              JSON.stringify(finishPosts.map(p => p.body)));
        check("the 24h limit is explained", /24 hours/i.test(d.lockText.textContent),
              JSON.stringify(d.lockText.textContent));
        check("the limit is shown as an error", d.lock.getAttribute("data-tone") === "error",
              String(d.lock.getAttribute("data-tone")));
    }

    /* ---- 4. start is refused with no subject ---- */
    {
        const d = buildDom("u1");
        load(d);
        fire(d.start, "click");
        check("start does nothing with no subject", d.card.getAttribute("data-state") === "idle",
              d.card.getAttribute("data-state"));
        check("start is explained", /Choose a subject/i.test(d.lockText.textContent),
              JSON.stringify(d.lockText.textContent));
        check("no interval leaked", d.intervals === 0, "intervals=" + d.intervals);
    }

    /* ---- 5. the finished session is never re-saved ---- */
    {
        const d = buildDom("u1");
        load(d);
        d.select.value = "3";
        fire(d.select, "change");
        await new Promise((r) => setTimeout(r, 0));
        fire(d.start, "click");
        d.tick(30000);
        fire(d.finish, "click");
        await new Promise((r) => setTimeout(r, 0));

        check("finish POSTed the elapsed seconds with the subject",
              JSON.stringify(d.posts.filter(p => p.url === "/finish").map(p => p.body)) === '[{"duration":30,"category_id":"3"}]',
              JSON.stringify(d.posts.filter(p => p.url === "/finish").map(p => p.body)));
        check("store is cleared after a successful finish",
              Object.keys(d.store).length === 0, JSON.stringify(Object.keys(d.store)));
        check("CSRF header is sent",
              d.posts.every(p => p.headers["X-CSRFToken"] === "test-csrf"));
    }

    /* ---- 6. store is scoped per user ---- */
    {
        const a = buildDom("user-1");
        load(a);
        const b = buildDom("user-2");
        load(b);
        a.select.value = "3";
        fire(a.select, "change");
        fire(a.start, "click");
        check("user-1 store key is scoped", Object.keys(a.store)[0] === "studynow.timer.user-1",
              JSON.stringify(Object.keys(a.store)));
        check("user-2 store is untouched", Object.keys(b.store).length === 0,
              JSON.stringify(Object.keys(b.store)));
    }

    /* ---- 7. restore re-syncs the subject with the server ---- */
    {
        const d = buildDom("u1");
        d.store["studynow.timer.u1"] = JSON.stringify({
            elapsed: 120000, startedAt: null, running: false, category: "5"
        });
        load(d);
        await new Promise((r) => setTimeout(r, 0));
        const sel = d.posts.filter(p => p.url === "/select-category");
        check("restore POSTs the subject back to the server", sel.length === 1,
              JSON.stringify(sel.map(p => p.body)));
        check("restore sends the right id",
              sel[0] && sel[0].body.category_id === "5", JSON.stringify(sel[0] && sel[0].body));
        check("restore keeps the paused session", d.card.getAttribute("data-state") === "paused",
              d.card.getAttribute("data-state"));
    }

    /* ---- 8. restore of a deleted subject discards cleanly ---- */
    {
        const d = buildDom("u1");
        d.store["studynow.timer.u1"] = JSON.stringify({
            elapsed: 120000, startedAt: null, running: false, category: "999"
        });
        load(d);
        check("a subject that no longer exists discards the session",
              d.card.getAttribute("data-state") === "idle", d.card.getAttribute("data-state"));
        check("the store is cleared", Object.keys(d.store).length === 0,
              JSON.stringify(Object.keys(d.store)));
        check("no interval leaked after restore-discard", d.intervals === 0,
              "intervals=" + d.intervals);
    }

    /* ---- 9. corrupt payload is survivable ---- */
    {
        const d = buildDom("u1");
        d.store["studynow.timer.u1"] = "{not json";
        load(d);
        check("a corrupt payload is discarded", Object.keys(d.store).length === 0,
              JSON.stringify(Object.keys(d.store)));
        check("a corrupt payload leaves the page usable",
              d.card.getAttribute("data-state") === "idle", d.card.getAttribute("data-state"));
    }

    /* ---- 10. no announcement at zero on load ---- */
    {
        const d = buildDom("u1");
        load(d);
        check("nothing is announced on a fresh page load", d.readoutLive.textContent === "",
              JSON.stringify(d.readoutLive.textContent));
    }

    /* ---- 11. discard is refused while a save is in flight ---- */
    {
        const d = buildDom("u1");
        load(d);
        d.select.value = "3";
        fire(d.select, "change");
        await new Promise((r) => setTimeout(r, 0));
        fire(d.start, "click");
        d.tick(5000);
        fire(d.finish, "click");
        check("discard is disabled during the save", d.discard.disabled === true,
              "discard.disabled=" + d.discard.disabled);
        fire(d.discard, "click");
        check("discard does not reset the clock mid-save",
              d.card.getAttribute("data-state") === "running",
              d.card.getAttribute("data-state"));
    }

    /* ---- 12. an error message survives the ticks that follow ---- */
    {
        const d = buildDom("u1");
        load(d);
        d.select.value = "3";
        fire(d.select, "change");
        await new Promise((r) => setTimeout(r, 0));
        fire(d.start, "click");

        /* an over-long run raises the error banner while the timer is still
           running; the next tick must not wipe it */
        d.tick(8 * 24 * 3600 * 1000);
        fire(d.finish, "click");
        await new Promise((r) => setTimeout(r, 0));

        check("the error is shown while running",
              /24 hours/i.test(d.lockText.textContent),
              JSON.stringify({ t: d.lockText.textContent, s: d.card.getAttribute("data-state") }));
        check("the running state is unchanged", d.card.getAttribute("data-state") === "running",
              d.card.getAttribute("data-state"));
        check("the banner is visible", d.lock.hidden === false, "lock.hidden=" + d.lock.hidden);
        check("it is toned as an error", d.lock.getAttribute("data-tone") === "error",
              String(d.lock.getAttribute("data-tone")));

        for (let i = 0; i < 20; i++) { d.tick(250); }

        check("the error message survives many ticks",
              /24 hours/i.test(d.lockText.textContent), JSON.stringify(d.lockText.textContent));
        check("the error tone survives many ticks",
              d.lock.getAttribute("data-tone") === "error", String(d.lock.getAttribute("data-tone")));
        check("the banner is still visible", d.lock.hidden === false, "lock.hidden=" + d.lock.hidden);

        /* and a deliberate restart clears it */
        d.select.disabled = false;
        fire(d.start, "click");
        check("starting over clears the stale error",
              /24 hours/i.test(d.lockText.textContent) === false,
              JSON.stringify(d.lockText.textContent));
    }

    /* ---- 13. a restore reattach failure is reported ---- */
    {
        const d = buildDom("u1");
        d.store["studynow.timer.u1"] = JSON.stringify({
            elapsed: 0, startedAt: d.clockNow() - 1000, running: true, category: "3"
        });
        load(d);
        d.awaitMicro();

        check("restore re-syncs the subject with the server",
              d.posts.some((p) => p.url === "/select-category"),
              JSON.stringify(d.posts.map((p) => p.url)));
        check("a successful restore is running again",
              d.card.getAttribute("data-state") === "running",
              d.card.getAttribute("data-state"));
    }

    /* ---- 14. guidance is re-derived, so it can never contradict the state ---- */
    {
        const d = buildDom("u1");
        load(d);

        check("with no subject the banner asks for one",
              /choose a subject/i.test(d.lockText.textContent), JSON.stringify(d.lockText.textContent));
        check("that guidance is not toned as an error",
              d.lock.getAttribute("data-tone") === null, String(d.lock.getAttribute("data-tone")));

        /* the user picks a subject: the old line must go, not linger */
        d.select.value = "3";
        fire(d.select, "change");
        await new Promise((r) => setTimeout(r, 0));

        check("choosing a subject replaces the stale prompt",
              /choose a subject/i.test(d.lockText.textContent) === false,
              JSON.stringify(d.lockText.textContent));
        check("it now invites the user to start",
              /press start/i.test(d.lockText.textContent), JSON.stringify(d.lockText.textContent));
        check("the invitation is not toned as an error",
              d.lock.getAttribute("data-tone") === null, String(d.lock.getAttribute("data-tone")));

        /* a failed select is a real error and must survive ticks */
        d.flags.failSelect = true;
        d.select.value = "5";
        fire(d.select, "change");
        await new Promise((r) => setTimeout(r, 0));

        check("a failed select is reported as an error",
              /could not be selected/i.test(d.lockText.textContent), JSON.stringify(d.lockText.textContent));
        check("the select reverts to the confirmed subject",
              d.select.value === "3", d.select.value);

        for (let i = 0; i < 10; i++) { d.tick(250); }
        check("the error survives ticks while idle",
              /could not be selected/i.test(d.lockText.textContent), JSON.stringify(d.lockText.textContent));
        check("the error keeps its tone",
              d.lock.getAttribute("data-tone") === "error", String(d.lock.getAttribute("data-tone")));

        /* and a later successful pick clears it */
        d.flags.failSelect = false;
        d.select.value = "3";
        fire(d.select, "change");
        await new Promise((r) => setTimeout(r, 0));

        check("a successful pick clears the stale error",
              /could not be selected/i.test(d.lockText.textContent) === false,
              JSON.stringify(d.lockText.textContent));
        check("and guidance returns",
              /press start/i.test(d.lockText.textContent), JSON.stringify(d.lockText.textContent));

        /* starting hides the banner entirely */
        fire(d.start, "click");
        check("starting hides the banner", d.lock.hidden === true, "lock.hidden=" + d.lock.hidden);
        check("and empties it", d.lockText.textContent === "", JSON.stringify(d.lockText.textContent));
    }

    /* ---- 15. full screen takes the timer over ---- */
    {
        const d = buildDom("u1");
        load(d);

        check("the toggle starts unpressed",
              d.fullscreen.getAttribute("aria-pressed") === "false",
              String(d.fullscreen.getAttribute("aria-pressed")));
        check("the toggle starts as an entry action",
              d.fullscreenLabel.textContent === "Full screen",
              JSON.stringify(d.fullscreenLabel.textContent));

        fire(d.fullscreen, "click");
        await d.awaitMicro();

        check("entering turns the focus view on",
              d.document.body.classList.contains("is-focusmode"),
              d.document.body.classList.toString());
        check("entering marks the button pressed",
              d.fullscreen.getAttribute("aria-pressed") === "true",
              String(d.fullscreen.getAttribute("aria-pressed")));
        check("the label becomes an exit action",
              d.fullscreenLabel.textContent === "Exit full screen",
              JSON.stringify(d.fullscreenLabel.textContent));
        check("native fullscreen follows the class",
              d.document.fullscreenElement === d.card,
              String(d.document.fullscreenElement));

        fire(d.fullscreen, "click");
        await d.awaitMicro();

        check("clicking again clears the focus view",
              !d.document.body.classList.contains("is-focusmode"),
              d.document.body.classList.toString());
        check("clicking again unpresses the button",
              d.fullscreen.getAttribute("aria-pressed") === "false",
              String(d.fullscreen.getAttribute("aria-pressed")));
        check("the label becomes an entry action again",
              d.fullscreenLabel.textContent === "Full screen",
              JSON.stringify(d.fullscreenLabel.textContent));
        check("native fullscreen is left behind",
              d.document.fullscreenElement === null,
              String(d.document.fullscreenElement));
    }

    /* ---- 16. the class works where there is no native fullscreen ---- */
    {
        const d = buildDom("u1");
        delete d.card.requestFullscreen;
        load(d);

        fire(d.fullscreen, "click");
        await d.awaitMicro();

        check("focus mode enters without the native API",
              d.document.body.classList.contains("is-focusmode"),
              d.document.body.classList.toString());
        check("and still marks the button pressed",
              d.fullscreen.getAttribute("aria-pressed") === "true",
              String(d.fullscreen.getAttribute("aria-pressed")));
        check("native fullscreen is simply absent",
              d.document.fullscreenElement === null,
              String(d.document.fullscreenElement));

        d.dispatchDoc("keydown", { key: "Escape" });
        check("Escape still leaves the focus view",
              !d.document.body.classList.contains("is-focusmode"),
              d.document.body.classList.toString());
        check("Escape leaves the button unpressed",
              d.fullscreen.getAttribute("aria-pressed") === "false",
              String(d.fullscreen.getAttribute("aria-pressed")));
    }

    /* ---- 17. a native exit is read back, not assumed ---- */
    {
        const d = buildDom("u1");
        load(d);
        fire(d.fullscreen, "click");
        await d.awaitMicro();
        check("the card took native fullscreen",
              d.document.fullscreenElement === d.card,
              String(d.document.fullscreenElement));

        /* the browser's own Esc clears fullscreenElement and fires the event */
        d.document.fullscreenElement = null;
        d.dispatchDoc("fullscreenchange");

        check("a native exit takes the focus view with it",
              !d.document.body.classList.contains("is-focusmode"),
              d.document.body.classList.toString());
        check("and unpresses the button",
              d.fullscreen.getAttribute("aria-pressed") === "false",
              String(d.fullscreen.getAttribute("aria-pressed")));
    }

    /* ---- 18. somebody else's fullscreen is none of our business ---- */
    {
        const d = buildDom("u1");
        load(d);

        /* Focus mode is off and something else on the page - a video, a
           dialog - takes the screen. Without the card check the handler would
           read any truthy fullscreenElement as an instruction to hide the
           chrome around the timer. */
        d.document.fullscreenElement = { foreign: true };
        d.dispatchDoc("fullscreenchange");

        check("another element's fullscreen does not start the focus view",
              !d.document.body.classList.contains("is-focusmode"),
              d.document.body.classList.toString());
        check("and the button stays unpressed",
              d.fullscreen.getAttribute("aria-pressed") === "false",
              String(d.fullscreen.getAttribute("aria-pressed")));
    }

    /* ---- 19. a refusal is survivable, and reported as nothing ---- */
    {
        const d = buildDom("u1");
        d.flags.failFullscreen = true;
        load(d);

        fire(d.fullscreen, "click");
        await d.awaitMicro();

        check("a refused entry still gives focus mode",
              d.document.body.classList.contains("is-focusmode"),
              d.document.body.classList.toString());
        check("and the button still reads as pressed",
              d.fullscreen.getAttribute("aria-pressed") === "true",
              String(d.fullscreen.getAttribute("aria-pressed")));
        check("native fullscreen did not come up",
              d.document.fullscreenElement === null,
              String(d.document.fullscreenElement));
    }

    {
        const d = buildDom("u1");
        load(d);
        fire(d.fullscreen, "click");
        await d.awaitMicro();

        d.flags.failExitFullscreen = true;
        fire(d.fullscreen, "click");
        await d.awaitMicro();

        check("a refused exit still leaves focus mode",
              !d.document.body.classList.contains("is-focusmode"),
              d.document.body.classList.toString());
        check("and the button is back to unpressed",
              d.fullscreen.getAttribute("aria-pressed") === "false",
              String(d.fullscreen.getAttribute("aria-pressed")));
    }

    check("no fullscreen refusal escaped as an unhandled rejection",
          unhandled.length === 0,
          JSON.stringify(unhandled.map((e) => String(e && e.message))));

    console.log("\n" + (failures === 0 ? "all behavioural checks passed" : failures + " failures"));
    process.exit(failures === 0 ? 0 : 1);
})();

