/* Shared UI behaviour: mobile navigation and toast dismissal.
   The timer has its own file; keep this one generic. */

(function () {
    "use strict";

    var navToggle = document.querySelector("[data-nav-toggle]");
    var nav = document.querySelector("[data-nav]");

    function setNav(open) {
        if (!nav || !navToggle) {
            return;
        }
        nav.setAttribute("data-open", open ? "true" : "false");
        navToggle.setAttribute("aria-expanded", open ? "true" : "false");
    }

    if (navToggle && nav) {
        navToggle.addEventListener("click", function () {
            setNav(nav.getAttribute("data-open") !== "true");
        });

        /* Following a link closes the panel, and so does Escape or a click
           outside it, which is what a keyboard user expects. */
        nav.addEventListener("click", function (event) {
            if (event.target.closest("a")) {
                setNav(false);
            }
        });

        document.addEventListener("keydown", function (event) {
            if (event.key === "Escape") {
                setNav(false);
            }
        });

        document.addEventListener("click", function (event) {
            if (!nav.contains(event.target) && !navToggle.contains(event.target)) {
                setNav(false);
            }
        });

        /* Rotating back to desktop must not leave the button looking open. */
        window.addEventListener("resize", function () {
            if (window.innerWidth > 760) {
                setNav(false);
            }
        });
    }

    function dismiss(alert) {
        alert.style.opacity = "0";
        alert.style.transform = "translateY(-6px)";
        window.setTimeout(function () {
            alert.remove();
        }, 160);
    }

    document.addEventListener("click", function (event) {
        var close = event.target.closest(".alert__close");
        if (close) {
            dismiss(close.closest(".alert"));
        }
    });

    document.querySelectorAll(".alert").forEach(function (alert) {
        window.setTimeout(function () {
            if (alert.isConnected) {
                dismiss(alert);
            }
        }, 6000);
    });

    /* Ask before destructive posts so a stray click cannot delete anything,
       and stop a second submit so a double click cannot save twice. */
    document.addEventListener("submit", function (event) {
        var form = event.target;
        var question = form.getAttribute("data-confirm");
        if (question && !window.confirm(question)) {
            event.preventDefault();
            return;
        }
        var button = form.querySelector('button[type="submit"]');
        if (button) {
            button.disabled = true;
        }
    });

    /* A saved session must not survive the account that produced it. */
    document.addEventListener("click", function (event) {
        var link = event.target.closest('a[href="/logout"]');
        if (!link) {
            return;
        }
        try {
            var user = document.body.getAttribute("data-timer-user") || "anon";
            window.localStorage.removeItem("studynow.timer." + user);
        } catch (error) {
            /* storage unavailable; nothing to clear */
        }
    });
})();
