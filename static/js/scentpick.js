// --------- 유틸: 현재 페이지가 chat이면 말풍선 숨김 ----------
(function () {
  try {
    var bubble = document.getElementById("chatbotToggle");
    if (!bubble) return;
    if (window.location.pathname.replace(/\/+$/, "") === "/chat") {
      bubble.style.display = "none";
    } else {
      bubble.style.display = "block";
    }
  } catch (e) {}
})();

// --------- 성별 선택 ----------
document.addEventListener("click", function (e) {
  if (e.target.classList.contains("gender-btn")) {
    document.querySelectorAll(".gender-btn").forEach(b => b.classList.remove("active"));
    e.target.classList.add("active");
  }
});

// --------- 사이드바 챗봇 ----------
(function () {
  var sidebar = document.getElementById("chatbotSidebar");
  var toggle = document.getElementById("chatbotToggle");
  var closeBtn = document.getElementById("closeChatbot");
  var msgBox = document.getElementById("sidebarChatMessages");
  var input = document.getElementById("sidebarChatInput");
  var sendBtn = document.getElementById("sidebarSendBtn");

  function open() { if (sidebar) sidebar.classList.add("active"); }
  function close() { if (sidebar) sidebar.classList.remove("active"); }
  function add(msg, isUser) {
    if (!msgBox) return;
    var div = document.createElement("div");
    div.className = "message" + (isUser ? " user" : "");
    div.innerHTML = '<div class="message-content">' + msg + "</div>";
    msgBox.appendChild(div);
    msgBox.scrollTop = msgBox.scrollHeight;
  }
  function send() {
    if (!input || !input.value.trim()) return;
    var txt = input.value.trim();
    input.value = "";
    add(txt, true);
    setTimeout(function () {
      add("도움을 드릴 수 있어서 기뻐요! 구체적으로 어떤 향수를 찾고 계신가요?", false);
    }, 600);
  }

  if (toggle) toggle.addEventListener("click", open);
  if (closeBtn) closeBtn.addEventListener("click", close);
  document.addEventListener("click", function (e) {
    if (sidebar && !sidebar.contains(e.target) && toggle && !toggle.contains(e.target)) {
      close();
    }
  });
  if (sendBtn) sendBtn.addEventListener("click", send);
  if (input) input.addEventListener("keypress", function (e) { if (e.key === "Enter") send(); });
})();

// --------- 태그/맵 필터 버튼 active ----------
(function () {
  document.querySelectorAll(".tag").forEach(tag => {
    tag.addEventListener("click", function () {
      document.querySelectorAll(".tag").forEach(t => t.classList.remove("active"));
      this.classList.add("active");
    });
  });
  document.querySelectorAll(".map-filter-btn").forEach(btn => {
    btn.addEventListener("click", function () {
      document.querySelectorAll(".map-filter-btn").forEach(b => b.classList.remove("active"));
      this.classList.add("active");
    });
  });
})();
