/**
 * KINETIC PURPLE — Interactive Controller
 * Handles live system metadata, smooth navigation scrolling, and brutalist card interactions.
 */

document.addEventListener('DOMContentLoaded', () => {
  initLiveClock();
  initSmoothScroll();
  initMarqueeSpeedAdjustment();
});

/**
 * Update real-time system clock in the metadata row
 */
function initLiveClock() {
  const timeEl = document.getElementById('live-time');
  if (!timeEl) return;

  function update() {
    const now = new Date();
    const utc = now.toISOString().substring(11, 19) + ' UTC';
    const local = now.toLocaleTimeString('en-US', { hour12: false });
    timeEl.textContent = `${local} [${utc}]`;
  }

  update();
  setInterval(update, 1000);
}

/**
 * Smooth scrolling for pill navigation and anchor links
 */
function initSmoothScroll() {
  document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
      const targetId = this.getAttribute('href');
      if (targetId === '#' || targetId === '') return;

      const targetEl = document.querySelector(targetId);
      if (targetEl) {
        e.preventDefault();
        targetEl.scrollIntoView({
          behavior: 'smooth',
          block: 'start'
        });
      }
    });
  });
}

/**
 * Optional micro-interaction: pause/accelerate marquee on hover
 */
function initMarqueeSpeedAdjustment() {
  const skewSection = document.querySelector('.marquee-skew-container');
  if (!skewSection) return;

  const leftRow = skewSection.querySelector('.marquee-content-left');
  const rightRow = skewSection.querySelector('.marquee-content-right');

  if (!leftRow || !rightRow) return;

  skewSection.addEventListener('mouseenter', () => {
    leftRow.style.animationPlayState = 'paused';
    rightRow.style.animationPlayState = 'paused';
  });

  skewSection.addEventListener('mouseleave', () => {
    leftRow.style.animationPlayState = 'running';
    rightRow.style.animationPlayState = 'running';
  });
}
