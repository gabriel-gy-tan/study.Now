/* Focus timer.
   Server contract: POST /select-category {category_id} to remember a pick,
   POST /finish {duration, category_id} to save, both with the X-CSRFToken
   header. The subject is repeated on /finish rather than relying on the
   earlier call having landed, because a select the browser restored on load
   never raises a change event. */

(function () {
    "use strict";

    var card = document.querySelector("[data-timer-card]");
    if (!card) {
        return;
    }

    /* Scoped per user so a shared browser cannot inherit someone else's
       session, and cleared on logout. */
    var STORE_KEY = "studynow.timer." + (card.getAttribute("data-user-id") || "anon");

    /* Must mirror MAX_SESSION_SECONDS in timer.py. */
    var MAX_SECONDS = 24 * 60 * 60;

    var readout = card.querySelector("[data-timer-readout]");
    var readoutLive = card.querySelector("[data-timer-readout-live]");
    var stateLabel = card.querySelector("[data-timer-state]");
    var subjectLabel = card.querySelector("[data-timer-subject]");
    var lock = card.querySelector("[data-timer-lock]");
    var lockText = card.querySelector("[data-timer-lock-text]");
    var categorySelect = document.querySelector("#category");
    var finishButton = document.querySelector("[data-timer-finish]");
    var finishLabel = card.querySelector("[data-timer-finish-label]");
    var fullscreenButton = card.querySelector("[data-timer-fullscreen]");
    var fullscreenLabel = card.querySelector("[data-timer-fullscreen-label]");

    var controls = {
        start: document.querySelector("[data-timer-start]"),
        pause: document.querySelector("[data-timer-pause]"),
        resume: document.querySelector("[data-timer-resume]"),
        discard: document.querySelector("[data-timer-discard]"),
        finish: finishButton
    };

    var baseTitle = document.title;
    var interval = null;
    var elapsed = 0;
    var startedAt = null;
    var running = false;
    /* Set once a session is saved so leaving the page cannot resurrect it. */
    var finished = false;
    /* A finish request is in flight; nothing else may cancel it. */
    var saving = false;
    /* The subject the server has been told about, so the label, the select
       and the session's attribution cannot drift apart. */
    var confirmedCategory = "";
    var lastAnnounced = 0;
    var lastFinishReady = false;

    function format(ms) {
        var total = Math.floor(ms / 1000);
        var hours = Math.floor(total / 3600);
        var minutes = Math.floor((total % 3600) / 60);
        var seconds = total % 60;
        return (
            String(hours).padStart(2, "0") +
            ":" +
            String(minutes).padStart(2, "0") +
            ":" +
            String(seconds).padStart(2, "0")
        );
    }

    function spokenDuration(ms) {
        var total = Math.floor(ms / 1000);
        var hours = Math.floor(total / 3600);
        var minutes = Math.floor((total % 3600) / 60);
        if (hours) {
            return hours + (hours === 1 ? " hour " : " hours ") + minutes + " minutes";
        }
        if (minutes) {
            return minutes + (minutes === 1 ? " minute" : " minutes");
        }
        return total + " seconds";
    }

    function currentElapsed() {
        return running ? elapsed + (Date.now() - startedAt) : elapsed;
    }

    function save() {
        if (finished) {
            return;
        }
        try {
            window.localStorage.setItem(
                STORE_KEY,
                JSON.stringify({
                    elapsed: elapsed,
                    startedAt: running ? startedAt : null,
                    running: running,
                    category: categorySelect ? categorySelect.value : ""
                })
            );
        } catch (error) {
            /* Private mode or storage disabled: the timer still works. */
        }
    }

    function clearSaved() {
        try {
            window.localStorage.removeItem(STORE_KEY);
        } catch (error) {
            /* nothing to clean up */
        }
    }

    function render() {
        var value = currentElapsed();
        readout.textContent = format(value);
        document.title = running ? format(value) + " · " + baseTitle : baseTitle;

        /* Announce sparingly: every minute is enough for a screen reader. */
        var minute = Math.floor(value / 60000);
        if (readoutLive && minute !== lastAnnounced && value > 0) {
            lastAnnounced = minute;
            readoutLive.textContent = "Timer at " + spokenDuration(value) + ".";
        }
    }

    function tick() {
        render();
        /* Finish becomes available the moment the clock passes zero, which
           happens between state changes, so watch for the flip rather than
           rewriting the attributes four times a second. */
        var ready = currentElapsed() > 0 && hasCategory() && !saving;
        if (ready !== lastFinishReady) {
            updateFinishAvailability();
        }
    }

    function setState() {
        if (running) {
            card.setAttribute("data-state", "running");
            stateLabel.textContent = "Focusing";
            document.body.classList.add("is-focusing");
            show("pause");
        } else if (elapsed > 0) {
            card.setAttribute("data-state", "paused");
            stateLabel.textContent = "Paused";
            document.body.classList.remove("is-focusing");
            show(null);
            controls.resume.hidden = false;
            controls.discard.hidden = false;
            controls.finish.hidden = false;
        } else {
            card.setAttribute("data-state", "idle");
            stateLabel.textContent = "Ready";
            document.body.classList.remove("is-focusing");
            show("start");
        }
        updateFinishAvailability();
    }

    function show(only) {
        Object.keys(controls).forEach(function (key) {
            var button = controls[key];
            if (button) {
                button.hidden = key !== only;
            }
        });
    }

    function hasCategory() {
        return Boolean(categorySelect && categorySelect.value);
    }

    /* `elapsed` is the accumulated base and stays 0 for the whole running
       phase, so it cannot be the only test: a subject chosen at second 0
       would still be editable at second 300. */
    function isLocked() {
        return running || elapsed > 0;
    }

    /* An error stays on screen until the state that produced it changes.
       Without this, an error shown while running would be wiped by the very
       next tick. Plain guidance is *not* sticky: it is re-derived from the
       current state on every tick, so it can never contradict what the user is
       actually looking at. */
    var messageSticky = false;

    function showMessage(text, tone) {
        messageSticky = tone === "error";
        if (!lock || !lockText) {
            return;
        }
        lock.hidden = false;
        lockText.textContent = text;
        if (tone) {
            lock.setAttribute("data-tone", tone);
        } else {
            lock.removeAttribute("data-tone");
        }
    }

    function clearMessage() {
        messageSticky = false;
        if (lockText) {
            lockText.textContent = "";
        }
        if (lock) {
            lock.removeAttribute("data-tone");
            lock.hidden = true;
        }
    }

    function updateFinishAvailability() {
        if (categorySelect) {
            categorySelect.disabled = isLocked();
        }

        if (controls.finish) {
            var ready = currentElapsed() > 0 && hasCategory();
            lastFinishReady = ready && !saving;
            controls.finish.disabled = saving || !ready;
            controls.finish.setAttribute("aria-disabled", String(saving || !ready));
        }

        if (controls.discard) {
            controls.discard.disabled = saving;
        }
        if (controls.resume) {
            controls.resume.disabled = saving;
        }

        if (!lock) {
            return;
        }
        /* Leave a real error alone: it is the only explanation the user has,
           and a tick would remove it a quarter of a second later. Plain
           guidance is re-derived below, so it can never go stale. */
        if (messageSticky) {
            return;
        }
        if (running) {
            clearMessage();
        } else if (!hasCategory()) {
            showMessage("Choose a subject before you start.");
        } else if (elapsed === 0) {
            showMessage("Press start when you are ready to focus.");
        } else {
            clearMessage();
        }
    }

    function csrfToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute("content") : "";
    }

    /* One place that owns the class, the button's pressed state and its label,
       so the three cannot disagree after an Esc or a native exit. */
    function setFocusMode(on) {
        document.body.classList.toggle("is-focusmode", on);
        if (fullscreenButton) {
            fullscreenButton.setAttribute("aria-pressed", String(on));
        }
        if (fullscreenLabel) {
            fullscreenLabel.textContent = on ? "Exit full screen" : "Full screen";
        }
    }

    function postJson(url, payload) {
        return fetch(url, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": csrfToken()
            },
            body: JSON.stringify(payload)
        });
    }

    function announceSubject() {
        if (!categorySelect || !subjectLabel) {
            return;
        }
        var option = categorySelect.options[categorySelect.selectedIndex];
        subjectLabel.textContent =
            option && option.value ? option.textContent.trim() : "No subject chosen";
        if (categorySelect.hasAttribute("data-empty")) {
            categorySelect.setAttribute("data-empty", String(!categorySelect.value));
        }
    }

    function selectCategory(id) {
        return postJson("/select-category", { category_id: id }).then(function (r) {
            if (!r.ok) {
                throw new Error("select failed");
            }
        });
    }

    function start() {
        if (saving) {
            return;
        }
        if (!hasCategory()) {
            showMessage("Choose a subject before you start.");
            if (categorySelect) {
                categorySelect.focus();
            }
            return;
        }
        /* A previous attempt that was navigated away from must not leave the
           guard set, or this session would never be persisted. */
        finished = false;
        clearMessage();
        startedAt = Date.now();
        running = true;
        window.clearInterval(interval);
        interval = window.setInterval(tick, 250);
        setState();
        render();
        save();
    }

    function pause() {
        if (saving) {
            return;
        }
        elapsed = currentElapsed();
        running = false;
        startedAt = null;
        window.clearInterval(interval);
        interval = null;
        setState();
        render();
        save();
    }

    function discard() {
        if (saving) {
            showMessage("This session is being saved. Wait a moment.", "error");
            return;
        }
        elapsed = 0;
        startedAt = null;
        running = false;
        window.clearInterval(interval);
        interval = null;
        clearSaved();
        clearMessage();
        setState();
        render();
    }

    function restore() {
        var raw;
        try {
            raw = window.localStorage.getItem(STORE_KEY);
        } catch (error) {
            return;
        }
        if (!raw) {
            return;
        }

        var data;
        try {
            data = JSON.parse(raw);
        } catch (error) {
            clearSaved();
            return;
        }

        if (!data || typeof data.elapsed !== "number") {
            clearSaved();
            return;
        }

        var hasOption = false;
        if (data.category && categorySelect) {
            hasOption = Array.prototype.some.call(categorySelect.options, function (o) {
                return o.value === String(data.category);
            });
            if (hasOption) {
                categorySelect.value = String(data.category);
                announceSubject();
                /* Setting .value fires no change event, so the server still
                   needs telling which subject this session belongs to. */
                confirmedCategory = String(data.category);
                selectCategory(data.category).catch(function () {
                    /* The session is still on screen, so do not throw the
                       stored copy away: the user can retry from Finish. */
                    showMessage(
                        "This session could not be reattached to the server.",
                        "error"
                    );
                });
            }
        }

        if (data.running && typeof data.startedAt === "number") {
            elapsed = data.elapsed;
            startedAt = data.startedAt;
            running = true;
            interval = window.setInterval(tick, 250);
        } else if (data.elapsed > 0) {
            elapsed = data.elapsed;
            running = false;
        } else {
            clearSaved();
            return;
        }

        if (!hasCategory()) {
            /* The subject is gone, so this session can never be saved. */
            discard();
        }
    }

    if (categorySelect) {
        categorySelect.addEventListener("change", function () {
            /* A wheel or keyboard can change a focused <select> without the
               user meaning to, and the server has already been told which
               subject this session belongs to. Put the value back. */
            if (isLocked()) {
                if (confirmedCategory) {
                    categorySelect.value = confirmedCategory;
                }
                announceSubject();
                showMessage("The subject is locked once a session has started.");
                return;
            }

            announceSubject();
            /* A previous "choose a subject" line is now wrong, and a failed
               select below puts its own error back. Re-derive the guidance so
               the banner always matches the current selection. */
            clearMessage();
            updateFinishAvailability();
            if (categorySelect.value) {
                selectCategory(categorySelect.value)
                    .then(function () {
                        confirmedCategory = categorySelect.value;
                    })
                    .catch(function () {
                        categorySelect.value = confirmedCategory;
                        announceSubject();
                        showMessage("That subject could not be selected. Try again.", "error");
                    });
            }
            save();
        });
    }

    if (controls.start) {
        controls.start.addEventListener("click", start);
    }
    if (controls.pause) {
        controls.pause.addEventListener("click", pause);
    }
    if (controls.resume) {
        controls.resume.addEventListener("click", start);
    }
    if (controls.discard) {
        controls.discard.addEventListener("click", discard);
    }

    if (controls.finish) {
        controls.finish.addEventListener("click", function () {
            var seconds = Math.floor(currentElapsed() / 1000);

            if (saving || seconds <= 0 || !hasCategory()) {
                return;
            }

            /* The server rejects anything over 24 hours with a 400 and no
               explanation, which would leave the user on a dead end with a
               reload restoring the same unfinishable session. */
            if (seconds > MAX_SECONDS) {
                showMessage(
                    "A single session can be at most 24 hours. Discard this one " +
                        "or finish it before the limit.",
                    "error"
                );
                return;
            }

            saving = true;
            updateFinishAvailability();
            if (finishLabel) {
                finishLabel.textContent = "Saving…";
            }

            /* The subject goes with the duration. POST /select-category is a
               side effect of the dropdown's change event, which never fires
               when the browser restores a select's value on load, so relying on
               it left the server with no subject and the save failed. */
            postJson("/finish", {
                duration: seconds,
                category_id: categorySelect ? categorySelect.value : ""
            })
                .then(function (response) {
                    if (!response.ok) {
                        throw new Error("save failed");
                    }
                    /* Stop before navigating: beforeunload calls save(), and an
                       unguarded write would restore this session on the way
                       back and allow it to be saved twice. */
                    finished = true;
                    clearSaved();
                    window.location.href = "/finish";
                })
                .catch(function () {
                    saving = false;
                    if (finishLabel) {
                        finishLabel.textContent = "Finish session";
                    }
                    showMessage("That session could not be saved. Try again.", "error");
                    updateFinishAvailability();
                });
        });
    }

    document.addEventListener("visibilitychange", function () {
        if (document.hidden) {
            save();
        }
    });

    window.addEventListener("beforeunload", save);

    /* Full-screen timer.
       The class does the work, because the browser fullscreen API is missing
       on iPhone Safari and refused without a user gesture elsewhere. The API
       is used on top where it exists, so the tab also leaves the window
       chrome, and Esc still exits because the browser handles that itself. */
    if (fullscreenButton) {
        fullscreenButton.addEventListener("click", function () {
            var entering = !document.body.classList.contains("is-focusmode");

            /* The class comes first: it is what actually shows the timer-only
               view, and it still works where the browser refuses native
               fullscreen. setFocusMode owns the class, the pressed state and
               the label together, so the three cannot drift apart. */
            setFocusMode(entering);

            if (entering) {
                if (card.requestFullscreen) {
                    /* Rejected when the document is not focused. The class is
                       already applied, so there is nothing to undo. */
                    card.requestFullscreen().catch(function () {});
                }
            } else if (document.exitFullscreen) {
                /* Also caught, for symmetry with the entry above and so a
                   refusal cannot surface as an unhandled rejection. */
                document.exitFullscreen().catch(function () {});
            }
        });
    }

    /* Esc, or a native exit, leaves fullscreen: the browser sets
       fullscreenElement back to null and tells us. Only the card is ours to
       answer for, so another element going fullscreen elsewhere in the page
       cannot turn the timer view on or off. */
    document.addEventListener("fullscreenchange", function () {
        var element = document.fullscreenElement;
        if (element && element !== card) {
            return;
        }
        setFocusMode(Boolean(element));
    });

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && document.body.classList.contains("is-focusmode") && !document.fullscreenElement) {
            setFocusMode(false);
        }
    });

    restore();
    announceSubject();
    confirmedCategory = categorySelect && categorySelect.value
        ? categorySelect.value
        : confirmedCategory;
    setState();
    render();
})();
