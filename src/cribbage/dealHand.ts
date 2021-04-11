import Card from "./Card";
import { Engine, sample } from "random-js";
import Hand from "./Hand";
import { List } from "immutable";

const DEALT_HAND_SIZE = 4;

export default (randomJsEngine: Engine, deck: readonly Card[]): Hand =>
  new Hand(List(sample(randomJsEngine, deck, DEALT_HAND_SIZE)));
