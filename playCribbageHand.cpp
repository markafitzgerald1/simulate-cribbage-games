/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

#include <iostream>
#include <vector>
#include <numeric>
#include <algorithm>
#include <random>
#include <cstdlib>
#include <chrono>
#include <list>

int main(int argc, char *argv[])
{
    int nHands = 862500;
    if (argc >= 2)
    {
        nHands = atoi(argv[1]);
    }

    std::vector<int> deck(52);
    std::iota(deck.begin(), deck.end(), 0);
    // std::cout << "Deck is: ";
    // for (auto i = deck.begin(); i != deck.end(); ++i)
    //     std::cout << *i << ' ';
    // std::cout << std::endl;

    std::vector<int> deal(8);

    auto mt19937 = std::mt19937{std::random_device{}()};
    auto startTimeNs = std::chrono::high_resolution_clock::now();
    for (auto hand = 0; hand < nHands; ++hand)
    {
        std::sample(deck.begin(), deck.end(), deal.begin(), 8, mt19937);
        std::shuffle(deal.begin(), deal.end(), mt19937);
        // std::cout << "Deal is: ";
        // for (auto card = deal.begin(); card != deal.end(); ++card)
        // {
        //     std::cout << *card << ' ';
        // }
        // std::cout << std::endl;

        std::list<int> hands[] = {
            std::list<int>(deal.begin(), deal.begin() + 4),
            std::list<int>(deal.begin() + 4, deal.end())};
        // std::cout << "Hands are: ";
        // for (auto handNumber = 0; handNumber < 2; handNumber++)
        // {
        //     for (auto card = hands[handNumber].begin(); card != hands[handNumber].end(); ++card)
        //     {
        //         std::cout << *card << ' ';
        //     }
        //     std::cout << ';';
        // }
        // std::cout << std::endl;

        int playerToPlay = 0;
        while (hands[0].size() + hands[1].size() > 0)
        {
            if (hands[playerToPlay].size() > 0)
            {
                int playerToPlayPlay = hands[playerToPlay].back();
                hands[playerToPlay].pop_back();
                // std::cout << "Player" << playerToPlay << "has a play:" << playerToPlayPlay << std::endl;
            }
            playerToPlay = (playerToPlay + 1) % 2;
        }
    }

    std::chrono::duration<double> elapsedDuration = std::chrono::high_resolution_clock::now() - startTimeNs;
    auto elapsedSeconds = elapsedDuration.count();
    std::cout << "Simulated " << nHands << " hands in " << elapsedSeconds << " s for " << (elapsedSeconds * 1000000000 / nHands) << " ns per hand" << std::endl;

    return 0;
}