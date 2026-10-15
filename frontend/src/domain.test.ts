import { describe, it, expect } from 'vitest';
import { buildTrip, formatMoney, safeUrl } from './domain';
describe('TripInput and safe display', () => {
  it('preserves exact money as a string and includes both dates', () => {
    const result = buildTrip({ departure_city: ' Москва ', destination: 'Казань', start_date:'2026-11-14', end_date:'2026-11-14', budget:'12345678901234567890,0001', currency:'RUB', travelers:'2', interests:'музеи, архитектура' });
    expect(result.data?.budget).toBe('12345678901234567890.0001');
    expect(result.data?.travelers).toBe(2);
    expect(result.data?.interests).toEqual(['музеи','архитектура']);
    expect(result.errors).toEqual({});
    expect(formatMoney('12345678901234567890.0001')).toBe('12 345 678 901 234 567 890,0001');
  });
  it('rejects exponents and unsafe URLs', () => {
    expect(safeUrl('javascript:alert(1)')).toBeNull();
    expect(safeUrl('https://example.com')).toBe('https://example.com/');
    const r=buildTrip({departure_city:'A',destination:'B',start_date:'2026-11-15',end_date:'2026-11-14',budget:'1e3',currency:'rub',travelers:'1.5',interests:''});
    expect(r.errors.budget).toBeTruthy(); expect(r.errors.end_date).toBeTruthy(); expect(r.errors.travelers).toBeTruthy();
  });
});
