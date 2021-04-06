export default class Suit {
  static readonly TOTAL_COUNT: number = 4;
  static readonly STRINGS: Array<string> = "♣♦♥♠".split("");

  readonly value: number;

  constructor(value: number) {
    if (value < 0 || value >= Suit.TOTAL_COUNT) {
      throw new RangeError(`Value must be between 0 and ${Suit.TOTAL_COUNT}.`);
    }

    this.value = value;
  }

  public toString = (): string => {
    return Suit.STRINGS[this.value];
  };
}
