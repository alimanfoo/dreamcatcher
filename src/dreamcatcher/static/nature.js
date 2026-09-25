"use strict";

const sunrise = 6 * 60;
const sunset = 18 * 60;
const sunrisePosition = 6;
const sunsetPosition = 94;

function updateSunPosition() {
  const now = new Date();
  const minutes = now.getHours() * 60 + now.getMinutes();
  const daylightDuration = sunset - sunrise;
  const isDaylight = minutes >= sunrise && minutes <= sunset;
  const daylightProgress = (minutes - sunrise) / daylightDuration;
  const sunPosition =
    sunrisePosition + (sunsetPosition - sunrisePosition) * daylightProgress;

  document.documentElement.style.setProperty(
    "--sun-opacity",
    isDaylight ? "1" : "0",
  );
  document.documentElement.style.setProperty("--sun-x", `${sunPosition}%`);
}

updateSunPosition();
window.setInterval(updateSunPosition, 60_000);
