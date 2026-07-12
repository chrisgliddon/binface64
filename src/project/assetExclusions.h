/**
* @copyright 2025 - Max Bebök
* @license MIT
*/
#pragma once

#include <algorithm>
#include <cctype>
#include <optional>
#include <regex>
#include <string>

namespace Project::AssetExclusions
{
  inline std::optional<std::string> normalize(std::string pattern)
  {
    auto first = pattern.find_first_not_of(" \t\r\n");
    auto last = pattern.find_last_not_of(" \t\r\n");
    if(first == std::string::npos)return std::nullopt;
    pattern = pattern.substr(first, last - first + 1);
    std::replace(pattern.begin(), pattern.end(), '\\', '/');
    while(pattern.starts_with("./"))pattern.erase(0, 2);
    if(pattern.starts_with("assets/"))pattern.erase(0, 7);

    if(pattern.empty() || pattern.front() == '/')return std::nullopt;
    if(pattern.size() >= 3 && std::isalpha(static_cast<unsigned char>(pattern[0]))
      && pattern[1] == ':' && pattern[2] == '/')return std::nullopt;

    size_t segmentStart = 0;
    while(segmentStart <= pattern.size()) {
      auto slash = pattern.find('/', segmentStart);
      auto segment = pattern.substr(segmentStart, slash - segmentStart);
      if(segment.empty() || segment == "." || segment == "..")return std::nullopt;
      if(slash == std::string::npos)break;
      segmentStart = slash + 1;
    }
    return pattern;
  }

  inline std::regex compile(const std::string &pattern)
  {
    std::string regex{"^"};
    for(size_t i = 0; i < pattern.size();) {
      const char c = pattern[i];
      if(c == '*') {
        if(i + 1 < pattern.size() && pattern[i + 1] == '*') {
          i += 2;
          if(i < pattern.size() && pattern[i] == '/') {
            regex += "(?:.*/)?";
            ++i;
          } else {
            regex += ".*";
          }
          continue;
        }
        regex += "[^/]*";
      } else if(c == '?') {
        regex += "[^/]";
      } else {
        if(std::string{".^$|()[]{}+\\"}.find(c) != std::string::npos)regex += '\\';
        regex += c;
      }
      ++i;
    }
    regex += '$';
    return std::regex{regex, std::regex::ECMAScript};
  }

  inline bool matches(const std::string &assetPath, const std::string &pattern)
  {
    auto normalized = normalize(pattern);
    if(!normalized)return false;
    auto slash = assetPath.find_last_of('/');
    auto basename = slash == std::string::npos ? assetPath : assetPath.substr(slash + 1);
    const auto &candidate = normalized->contains('/') ? assetPath : basename;
    return std::regex_match(candidate, compile(*normalized));
  }
}
