// scentlab/static/js/product_detail.js

// HTML에서 데이터를 읽어와서 JavaScript 객체로 변환하는 함수
function loadDataFromHTML() {
  const container = document.getElementById('data-container');
  if (!container) return;

  // GENDER 데이터 로드
  window.genderData = {};
  const genderGroup = container.querySelector('[data-type="gender"]');
  if (genderGroup) {
    const genderItems = genderGroup.querySelectorAll('[data-key]');
    genderItems.forEach(item => {
      window.genderData[item.dataset.key] = {
        label: item.dataset.label,
        value: item.dataset.value,
        percentage: item.dataset.percentage
      };
    });
  }

  // SEASON 데이터 로드
  window.seasonData = {};
  const seasonGroup = container.querySelector('[data-type="season"]');
  if (seasonGroup) {
    const seasonItems = seasonGroup.querySelectorAll('[data-key]');
    seasonItems.forEach(item => {
      window.seasonData[item.dataset.key] = {
        label: item.dataset.label,
        value: item.dataset.value,
        percentage: item.dataset.percentage
      };
    });
  }

  // TIME 데이터 로드
  window.timeData = {};
  const timeGroup = container.querySelector('[data-type="time"]');
  if (timeGroup) {
    const timeItems = timeGroup.querySelectorAll('[data-key]');
    timeItems.forEach(item => {
      window.timeData[item.dataset.key] = {
        label: item.dataset.label,
        value: item.dataset.value,
        percentage: item.dataset.percentage
      };
    });
  }

  // NOTES 데이터 로드
  window.notesData = {};
  const notesGroup = container.querySelector('[data-type="notes"]');
  if (notesGroup) {
    const notesItems = notesGroup.querySelectorAll('[data-key]');
    notesItems.forEach(item => {
      window.notesData[item.dataset.key] = {
        label: item.dataset.label,
        value: item.dataset.value,
        percentage: item.dataset.percentage
      };
    });
  }
}

// 데이터 바 생성 헬퍼 함수
function createDataBar(label, value, percentage, isPercentage = true) {
  const displayValue = isPercentage ? `${value}%` : value;
  const barWidth = Math.max(parseFloat(percentage) || 0, 2); // 최소 2% 너비 보장

  return `
    <div class="data-item">
      <div class="data-label">${label}</div>
      <div class="data-bar-container">
        <div class="data-bar-fill" style="width: ${barWidth}%;"></div>
        <div class="data-value">${displayValue}</div>
      </div>
    </div>
  `;
}

// 데이터 초기화 함수
function initializeDataPanels() {
  // 데이터 컨테이너들
  const genderContainer = document.getElementById('gender-data');
  const seasonContainer = document.getElementById('season-data');
  const timeContainer = document.getElementById('time-data');
  const notesContainer = document.getElementById('notes-data');

  // GENDER 데이터
  if (genderContainer && window.genderData) {
    Object.values(window.genderData).forEach(item => {
      genderContainer.innerHTML += createDataBar(item.label, item.value, item.percentage);
    });
  }

  // SEASON 데이터 - 봄-여름-가을-겨울 순으로 정렬
  if (seasonContainer && window.seasonData) {
    // 계절 순서 정의
    const seasonOrder = ['봄', '여름', '가을', '겨울'];

    // 계절 데이터를 순서대로 정렬
    const sortedSeasons = seasonOrder.map(season => {
      return Object.values(window.seasonData).find(item => item.label === season);
    }).filter(item => item); // undefined 제거

    sortedSeasons.forEach(item => {
      seasonContainer.innerHTML += createDataBar(item.label, item.value, item.percentage);
    });
  }

  // TIME 데이터
  if (timeContainer && window.timeData) {
    Object.values(window.timeData).forEach(item => {
      timeContainer.innerHTML += createDataBar(item.label, item.value, item.percentage);
    });
  }

  // NOTES 데이터 - 전체 표시 (값 순으로 정렬)
  if (notesContainer && window.notesData) {
    // 노트 데이터를 값 순으로 정렬하여 전체 표시
    const sortedNotes = Object.values(window.notesData)
      .sort((a, b) => parseFloat(b.percentage) - parseFloat(a.percentage));

    sortedNotes.forEach(item => {
      notesContainer.innerHTML += createDataBar(item.label, item.value, item.percentage, false);
    });
  }
}

// CSRF 토큰 가져오기 함수
function getCookie(name) {
  let cookieValue = null;
  if (document.cookie && document.cookie !== '') {
    const cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, name.length + 1) === (name + '=')) {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}

// 즐겨찾기 버튼 기능
function initializeFavoriteButton() {
  const favoriteBtn = document.querySelector(".favorite-btn");

  if (favoriteBtn) {
    favoriteBtn.addEventListener("click", async () => {
      const isCurrentlyActive = favoriteBtn.classList.contains("active");
      if (isCurrentlyActive) {
        if (!confirm("이 향수를 즐겨찾기에서 제거하시겠습니까?")) {
          return;
        }
      }

      try {
        const response = await fetch('/scentpick/api/toggle-favorite/', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
          },
          body: JSON.stringify({
            perfume_id: favoriteBtn.dataset.perfumeId
          })
        });

        if (response.ok) {
          const data = await response.json();
          if (data.success) {
            favoriteBtn.classList.toggle('active');
            if (favoriteBtn.classList.contains('active')) {
              favoriteBtn.innerHTML = '<span class="action-icon">⭐</span> 즐겨찾기';
            } else {
              favoriteBtn.innerHTML = '<span class="action-icon">⭐</span> 즐겨찾기';
            }
          }
        } else {
          const errorData = await response.json();
          alert(errorData.message || '즐겨찾기 처리 중 오류가 발생했습니다.');
        }
      } catch (error) {
        console.error('Error:', error);
        alert('즐겨찾기 처리 중 오류가 발생했습니다.');
      }
    });
  }
}

// 좋아요/싫어요 버튼 기능
async function handleLikeDislike(button, action) {
  const isCurrentlyActive = button.classList.contains("active");

  if (isCurrentlyActive) {
    if (!confirm(`이 향수에 대한 ${action === 'like' ? '좋아요' : '싫어요'}를 취소하시겠습니까?`)) {
      return;
    }
  }

  try {
    const response = await fetch('/scentpick/api/toggle-like-dislike/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCookie('csrftoken')
      },
      body: JSON.stringify({
        perfume_id: button.dataset.perfumeId,
        action: action
      })
    });

    if (response.ok) {
      const data = await response.json();
      if (data.success) {
        // 모든 버튼 초기화
        const likeBtn = document.querySelector(".like-btn");
        const dislikeBtn = document.querySelector(".dislike-btn");

        likeBtn.classList.remove('active');
        dislikeBtn.classList.remove('active');
        likeBtn.style.background = '';
        likeBtn.style.color = '';
        likeBtn.style.borderColor = '';
        dislikeBtn.style.background = '';
        dislikeBtn.style.color = '';
        dislikeBtn.style.borderColor = '';

        if (data.current_action === 'like') {
          likeBtn.classList.add('active');
          likeBtn.style.background = '#e53e3e';  // 빨간색
          likeBtn.style.color = 'white';
          likeBtn.style.borderColor = '#e53e3e';  // 빨간색
        } else if (data.current_action === 'dislike') {
          dislikeBtn.classList.add('active');
          dislikeBtn.style.background = '#718096';
          dislikeBtn.style.color = 'white';
          dislikeBtn.style.borderColor = '#718096';
        }
      } else {
        alert(data.message || '피드백 처리 중 오류가 발생했습니다.');
      }
    } else {
      const errorData = await response.json();
      alert(errorData.message || '피드백 처리 중 오류가 발생했습니다.');
    }
  } catch (error) {
    console.error('Error:', error);
    alert('피드백 처리 중 오류가 발생했습니다.');
  }
}

function initializeLikeDislikeButtons() {
  const likeBtn = document.querySelector(".like-btn");
  const dislikeBtn = document.querySelector(".dislike-btn");

  if (likeBtn) {
    likeBtn.addEventListener("click", () => handleLikeDislike(likeBtn, 'like'));
  }
  if (dislikeBtn) {
    dislikeBtn.addEventListener("click", () => handleLikeDislike(dislikeBtn, 'dislike'));
  }
}

// 구매 버튼 기능
function initializeBuyButton() {
  const buyBtn = document.getElementById('buy-btn');
  if (buyBtn) {
    buyBtn.addEventListener('click', function () {
      const url = this.dataset.url;
      if (url && url !== '#') {
        window.open(url, '_blank');
      } else {
        alert('구매 링크가 없습니다.');
      }
    });
  }
}

// DOM 로드 완료 후 실행
document.addEventListener('DOMContentLoaded', function () {
  // 데이터 로드 및 초기화
  loadDataFromHTML();

  // 약간의 지연 후 데이터 패널 초기화 (JSON 파싱 완료 대기)
  setTimeout(() => {
    initializeDataPanels();
  }, 100);

  // 기타 기능 초기화
  initializeFavoriteButton();
  initializeLikeDislikeButtons();
  initializeBuyButton();
});