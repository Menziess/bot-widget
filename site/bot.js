// The face on this page: it follows the pointer, can be grabbed and thrown, and answers a few questions.
(function () {
  var F = window.BotFace, canvas = document.getElementById("bot-canvas");
  var stage = document.getElementById("stage");
  if (!F || !canvas || !canvas.getContext || !window.Path2D) return;

  var ctx = canvas.getContext("2d");
  var reduced = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  var root = document.getElementById("bot"), hit = document.getElementById("bot-hit");
  var bubble = document.getElementById("bubble"), log = document.getElementById("log");
  var form = document.getElementById("ask"), input = document.getElementById("ask-text");
  var chips = document.getElementById("chips");

  var PAD = 9;                       // room around the face for squash, lean and a hop, in face units
  var u, dpr, k;                     // css px per face unit, device pixels per css px, device px per face unit
  var anim = new F.Animator();
  var x = 0, y = 0;                  // face centre in viewport px
  var vx = 0, vy = 0;                // px per second
  var homed = true;                  // still sitting at its place in the page
  var dragging = null, coasting = false, returning = false, happyUntil = 0;
  var pointer = null, pointerAt = 0;
  var mood = "idle", cycleI = 0, cycleLeft = 0, pose = "idle";
  var thinking = false, pinned = false, sayUntil = 0, bubbleKept = 0;

  function layout() {
    u = window.innerWidth < 640 ? 2.3 : 3;
    dpr = Math.min(window.devicePixelRatio || 1, 3);
    k = u * dpr;
    var box = (F.SIZE + 2 * PAD) * u;
    canvas.width = Math.round(box * dpr); canvas.height = Math.round(box * dpr);
    canvas.style.width = canvas.style.height = box + "px";
    root.style.width = root.style.height = box + "px";
    var d = 2 * F.R * u * 1.04;
    hit.style.width = hit.style.height = d + "px";
    hit.style.left = hit.style.top = (box - d) / 2 + "px";
    stage.style.width = stage.style.height = F.SIZE * u + "px";
    clamp();
    draw();
  }

  function draw() { F.draw(ctx, anim.value, k, PAD); }

  function bounds() {
    var r = F.R * u * 1.1;
    return { l: r, t: r, r: window.innerWidth - r, b: window.innerHeight - r };
  }

  // Returns true when it hit an edge: -1/1 for the side, so the caller can flatten the face against it.
  function clamp() {
    var b = bounds(), hitX = 0, hitY = 0;
    if (x < b.l) { x = b.l; hitX = -1; } else if (x > b.r) { x = b.r; hitX = 1; }
    if (y < b.t) { y = b.t; hitY = -1; } else if (y > b.b) { y = b.b; hitY = 1; }
    return [hitX, hitY];
  }

  function place() {
    var box = (F.SIZE + 2 * PAD) * u;
    root.style.transform = "translate3d(" + (x - box / 2) + "px," + (y - box / 2) + "px,0)";
    if (bubble.dataset.open === "true") placeBubble();
  }

  function home() {
    var r = stage.getBoundingClientRect();
    x = r.left + r.width / 2; y = r.top + r.height / 2;
  }

  // ── Mood: what the face wants to do when nobody is holding it ──────────

  function setPose(name) {
    var p = F.POSES[name];
    anim.aim({ dx: p[0], dy: p[1], scale: p[2], converge: 0, lift: 0 });
    pose = name;
  }

  function cycle(ms) {
    var m = thinking ? "work" : "idle";
    if (m !== mood) { mood = m; cycleI = 0; cycleLeft = 0; }
    cycleLeft -= ms;
    if (cycleLeft <= 0) {
      var step = F.CYCLE[mood][cycleI % F.CYCLE[mood].length];
      cycleI++; cycleLeft = step[1]; setPose(step[0]);
    }
  }

  function aim(now, ms, speed) {
    if (speed > 20 || dragging || coasting || returning) {
      var stretch = Math.min(speed / 1200, 0.10) * (Math.abs(vx) - Math.abs(vy)) / (speed + 1e-6);
      anim.aim({ sx: 1 + stretch, sy: 1 - stretch, lean: Math.max(-12, Math.min(12, vx / 70)) });
    } else anim.aim({ sx: 1, sy: 1, lean: 0 });

    if (dragging || now < happyUntil) {
      var moving = dragging && speed > 20;
      anim.aim({
        happy: moving ? 0.5 : 1, converge: 0, scale: 1, lift: 0,
        dx: moving ? Math.max(-8, Math.min(8, vx / speed * 8)) : 0,
        dy: moving ? Math.max(-8, Math.min(8, vy / speed * 8)) : 0
      });
      return;
    }
    anim.aim({ happy: 0 });
    if (!thinking && pointer && now - pointerAt < 6000) {
      var g = F.gaze((pointer[0] - x) / u, (pointer[1] - y) / u);
      anim.aim({ dx: g.dx, dy: g.dy, converge: g.converge, scale: g.scale, lift: 0 });
      cycleLeft = 0;
      return;
    }
    cycle(ms);
  }

  // ── The loop ────────────────────────────────────────────────────────

  var last = 0, px = 0, py = 0;
  function frame(t) {
    requestAnimationFrame(frame);
    var dt = last ? Math.min((t - last) / 1000, 0.05) : 0.016;
    last = t;
    if (!dt) return;
    var now = performance.now();

    if (homed && !dragging && !coasting) { home(); clamp(); }
    if (coasting) coast(dt);
    if (returning) glideHome(dt);

    // Speed from what the face actually did, so a held pointer that stops also settles.
    var nvx = (x - px) / dt, nvy = (y - py) / dt;
    if (dragging || coasting || returning) { vx += (nvx - vx) * 0.35; vy += (nvy - vy) * 0.35; }
    else { vx = vy = 0; }
    px = x; py = y;

    aim(now, dt * 1000, Math.hypot(vx, vy));
    var moving = anim.step(dt);
    if (moving || dragging || coasting) draw();
    place();

    if (sayUntil && now > sayUntil && !pinned && now > bubbleKept) closeBubble();
  }

  function glideHome(dt) {
    var r = stage.getBoundingClientRect(), hx = r.left + r.width / 2, hy = r.top + r.height / 2;
    var ease = 1 - Math.exp(-dt * 6);
    x += (hx - x) * ease; y += (hy - y) * ease;
    if (Math.hypot(hx - x, hy - y) < 2) {
      returning = false; homed = true; anim.kick("sy", -1.2); document.body.classList.remove("away");
    }
  }

  function coast(dt) {
    var decay = Math.pow(0.9, dt / 0.016);
    vx *= decay; vy *= decay;
    x += vx * dt; y += vy * dt;
    var edge = clamp();
    if (edge[0]) { anim.kick("sx", -0.9); vx = -vx * 0.55; }
    if (edge[1]) { anim.kick("sy", -0.9); vy = -vy * 0.55; }
    if (Math.abs(vx) < 80 && Math.abs(vy) < 80) {
      coasting = false; vx = vy = 0; anim.kick("sy", -1.2); homed = false;
      document.body.classList.add("away");
    }
  }

  // ── Grabbing and throwing ───────────────────────────────────────────

  hit.addEventListener("pointerdown", function (e) {
    if (e.button !== 0) return;
    hit.setPointerCapture(e.pointerId);
    coasting = false; returning = false; homed = false;
    document.body.classList.add("away");
    dragging = { id: e.pointerId, ox: x, oy: y, sx: e.clientX, sy: e.clientY, moved: 0 };
    root.classList.add("grabbed");
    anim.kick("sy", -0.8);
    e.preventDefault();
  });
  hit.addEventListener("pointermove", function (e) {
    pointer = [e.clientX, e.clientY]; pointerAt = performance.now();
    if (!dragging || e.pointerId !== dragging.id) return;
    dragging.moved = Math.max(dragging.moved, Math.abs(e.clientX - dragging.sx) + Math.abs(e.clientY - dragging.sy));
    x = dragging.ox + e.clientX - dragging.sx; y = dragging.oy + e.clientY - dragging.sy;
    clamp();
  });
  function release(e) {
    if (!dragging || e.pointerId !== dragging.id) return;
    var click = dragging.moved < 5 && e.type === "pointerup";
    dragging = null;
    root.classList.remove("grabbed");
    if (click) {
      togglePin();
      happyUntil = performance.now() + 600;
    } else if (!reduced && Math.hypot(vx, vy) > 500) {
      coasting = true;
    } else {
      anim.kick("sy", -1.2); vx = vy = 0;
    }
  }
  hit.addEventListener("keydown", function (e) {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); togglePin(); }
  });
  hit.addEventListener("pointerup", release);
  hit.addEventListener("pointercancel", release);

  document.getElementById("home").addEventListener("click", function () {
    if (!homed) { coasting = false; returning = true; }
  });

  window.addEventListener("pointermove", function (e) {
    pointer = [e.clientX, e.clientY]; pointerAt = performance.now();
  }, { passive: true });
  document.addEventListener("pointerleave", function () { pointer = null; });
  window.addEventListener("resize", function () { layout(); });

  // ── Bubble and talking ──────────────────────────────────────────────

  // Above the face if there is room, else beside it, else below.
  function placeBubble() {
    var w = bubble.offsetWidth, h = bubble.offsetHeight, gap = F.R * u + 10, vw = window.innerWidth, vh = window.innerHeight;
    var side = "above", left, top, tail;
    if (y - gap - h > 8) {
      left = Math.max(8, Math.min(vw - w - 8, x - w * 0.25)); top = y - gap - h; tail = x - left;
    } else if (x + gap + w < vw - 8 || x - gap - w > 8) {
      side = x + gap + w < vw - 8 ? "right" : "left";
      left = side === "right" ? x + gap : x - gap - w;
      top = Math.max(8, Math.min(vh - h - 8, y - h / 2)); tail = y - top;
    } else {
      side = "below";
      left = Math.max(8, Math.min(vw - w - 8, x - w * 0.25)); top = Math.min(vh - h - 8, y + gap); tail = x - left;
    }
    var along = side === "above" || side === "below" ? w : h;
    bubble.style.transform = "translate3d(" + left + "px," + top + "px,0)";
    bubble.style.setProperty("--tail", Math.max(18, Math.min(along - 18, tail)) + "px");
    bubble.dataset.side = side;
  }

  function openBubble() { bubble.dataset.open = "true"; bubble.setAttribute("aria-hidden", "false"); placeBubble(); }
  function closeBubble() { bubble.dataset.open = "false"; bubble.setAttribute("aria-hidden", "true"); sayUntil = 0; }

  bubble.addEventListener("pointerenter", function () { bubbleKept = performance.now() + 4000; });
  bubble.addEventListener("pointermove", function () { bubbleKept = performance.now() + 4000; });

  function add(role, text) {
    var line = document.createElement("p");
    line.className = role;
    line.textContent = text;
    log.appendChild(line);
    while (log.children.length > 8) log.removeChild(log.firstChild);
    log.scrollTop = log.scrollHeight;
    return line;
  }

  function say(text, seconds) {
    if (pinned) return;
    log.textContent = "";
    add("bot", text);
    bubble.classList.add("say");
    bubble.classList.remove("chat");
    sayUntil = performance.now() + seconds * 1000;
    openBubble();
  }

  function togglePin() {
    if (pinned) { pinned = false; closeBubble(); return; }
    pinned = true;
    bubble.classList.remove("say"); bubble.classList.add("chat");
    if (!log.children.length || bubble.dataset.greeted !== "chat") {
      log.textContent = "";
      add("bot", "I'm a small demo: I only know about Bot Widget. Download it and I'll talk to your real bot.");
      bubble.dataset.greeted = "chat";
    }
    openBubble();
    setTimeout(function () { input.focus({ preventScroll: true }); }, 30);
  }

  var ANSWERS = [
    [/\b(hi|hello|hey|hoi|yo)\b/, "Hi! Ask me how to install me, what I need, or what I can do."],
    [/install|download|get you|setup|set up|start|run/, "On a Mac: unzip, drag Bot Widget into Applications and open it. On Windows: run the installer. On Linux: unpack the archive and run ./botwidget/install.sh. With uv, one line does it everywhere: uv tool install git+https://github.com/Menziess/bot-widget"],
    [/windows|linux|mac|system|platform|support/, "I run on macOS, Windows and Linux. The download button above picks the right one for you."],
    [/openbot|grok/, "I'm only the face. I talk to OpenBot or Grok Bot on your computer; without either I tell you so and point you to both."],
    [/free|cost|price|pay|licen|open source/, "Free, and the source is on GitHub."],
    [/privacy|data|private|secure|safe|track|send/, "I talk to the bot on your own machine. The only thing I ask the internet is whether there is a newer release on GitHub, and that can be switched off."],
    [/update/, "I check GitHub for a newer release, download it, verify its checksum and restart into it when nobody is using me."],
    [/click|chat|bubble|type|talk|use/, "Click my face to open this bubble and type to your bot. While it works I read, and the bubble turns into a thought cloud. Right-click me to switch bots and open Settings."],
    [/who|what are|what do|about|do you do|purpose/, "I'm a small animated face for your OpenBot or Grok Bot. I sit on your desktop, look at your pointer, show the latest answer and open a chat when you click me."],
    [/throw|drag|move|grab|fling|toss|play/, "Grab me and fling me around the window. I do the same on your desktop."],
    [/thank|nice|cool|great|love/, "Thank you! Now download me and I'll keep you company."],
    [/joke/, "Why did the bot sit on my desktop? To keep an eye on things. I have two."]
  ];
  var FALLBACK = "I'm only a demo and I know a few things: installing me, which systems I run on, OpenBot and Grok Bot, privacy and updates.";

  function answer(text) {
    var q = text.toLowerCase();
    for (var i = 0; i < ANSWERS.length; i++) if (ANSWERS[i][0].test(q)) return ANSWERS[i][1];
    return FALLBACK;
  }

  var typing = 0;
  function reply(text) {
    clearInterval(typing);
    var line = add("bot", ""), n = 0;
    typing = setInterval(function () {
      n = Math.min(text.length, n + 2);
      line.textContent = text.slice(0, n);
      log.scrollTop = log.scrollHeight;
      if (n >= text.length) {
        clearInterval(typing);
        happyUntil = performance.now() + 700; anim.kick("sy", 0.8);
      }
    }, 18);
  }

  function ask(text) {
    text = text.trim();
    if (!text || thinking) return;
    add("you", text);
    thinking = true; bubble.classList.add("thinking");
    var dots = add("bot dots", "");
    dots.innerHTML = "<i></i><i></i><i></i>";
    setTimeout(function () {
      thinking = false; bubble.classList.remove("thinking");
      if (dots.parentNode) dots.parentNode.removeChild(dots);
      reply(answer(text));
    }, 700 + Math.random() * 600);
  }

  form.addEventListener("submit", function (e) { e.preventDefault(); var t = input.value; input.value = ""; ask(t); });
  chips.addEventListener("click", function (e) {
    if (e.target.tagName === "BUTTON") ask(e.target.textContent);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && pinned) { pinned = false; closeBubble(); }
  });

  // ── Go ──────────────────────────────────────────────────────────────

  layout();
  home(); px = x; py = y;
  document.body.classList.add("live");
  requestAnimationFrame(frame);
  if (!reduced) setTimeout(function () { say("Hi! Grab me and throw me, or click me to talk.", 9); }, 1200);
})();
