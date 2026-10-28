"use strict";

const sunrise = 6 * 60;
const sunset = 18 * 60;
const minutesPerDay = 24 * 60;
const startPosition = 6;
const endPosition = 94;

function updateCelestialPositions() {
  const now = new Date();
  const minutes = now.getHours() * 60 + now.getMinutes();
  const daylightDuration = sunset - sunrise;
  const isDaylight = minutes >= sunrise && minutes < sunset;
  const daylightProgress = (minutes - sunrise) / daylightDuration;
  const sunPosition =
    startPosition + (endPosition - startPosition) * daylightProgress;
  const nightDuration = minutesPerDay - daylightDuration;
  const nightMinutes =
    minutes >= sunset ? minutes - sunset : minutes + minutesPerDay - sunset;
  const nightProgress = nightMinutes / nightDuration;
  const moonPosition =
    startPosition + (endPosition - startPosition) * nightProgress;
  const isNight = minutes < sunrise || minutes >= sunset;

  document.documentElement.style.setProperty(
    "--sun-opacity",
    isDaylight ? "1" : "0",
  );
  document.documentElement.style.setProperty("--sun-x", `${sunPosition}%`);
  document.documentElement.style.setProperty(
    "--moon-opacity",
    isNight ? "1" : "0",
  );
  document.documentElement.style.setProperty("--moon-x", `${moonPosition}%`);
}

updateCelestialPositions();
window.setInterval(updateCelestialPositions, 60_000);
