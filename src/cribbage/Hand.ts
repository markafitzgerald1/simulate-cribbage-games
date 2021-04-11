import { List } from "immutable";
import Card from "./Card";

export default class Hand {
  constructor(public readonly cards: List<Card>) {}
}
