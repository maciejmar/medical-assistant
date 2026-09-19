export function ageFromBirthDate(birthDate: string | null, now: Date = new Date()): number | null {
  if (!birthDate) {
    return null;
  }
  const born = new Date(birthDate);
  if (Number.isNaN(born.getTime())) {
    return null;
  }
  let age = now.getFullYear() - born.getFullYear();
  const beforeBirthday =
    now.getMonth() < born.getMonth() ||
    (now.getMonth() === born.getMonth() && now.getDate() < born.getDate());
  if (beforeBirthday) {
    age -= 1;
  }
  return age;
}

export function formatDuration(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
}

export function emptyToNull(value: string | null | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed ? trimmed : null;
}
