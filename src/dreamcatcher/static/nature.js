"use strict";

const sunrise = 6 * 60;
const sunset = 18 * 60;
const minutesPerDay = 24 * 60;
const startPosition = 6;
const endPosition = 94;

// The root's data-sky says whether the sun or the moon is up, and the
// stylesheet shows each, and the motifs that follow them, from it.
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

  document.documentElement.dataset.sky = isDaylight ? "day" : "night";
  document.documentElement.style.setProperty("--sun-x", `${sunPosition}%`);
  document.documentElement.style.setProperty("--moon-x", `${moonPosition}%`);
}

updateCelestialPositions();
window.setInterval(updateCelestialPositions, 60_000);
